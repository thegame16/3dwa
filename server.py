"""Ɛdwa's small, self-hosted inventory and authentication server.

Run with: python server.py
The server binds to localhost by default. Put a production deployment behind HTTPS.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "forma.sqlite3"
SESSION_COOKIE = "forma_session"
SESSION_TTL = 60 * 60 * 24 * 14
MAX_BODY = 10 * 1024 * 1024
PBKDF2_ROUNDS = 310_000
ALLOWED_STATIC = {
    "/", "/index.html", "/app.js", "/styles.css", "/public/images/modern-villa.jpg"
}
LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def connect_db() -> sqlite3.Connection:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        class PostgresConnection:
            def __init__(self):
                self.connection = psycopg.connect(database_url, row_factory=dict_row)

            def __enter__(self):
                self.connection.__enter__()
                return self

            def __exit__(self, *args):
                return self.connection.__exit__(*args)

            def execute(self, query, params=()):
                return self.connection.execute(query.replace("?", "%s"), params)

            def executescript(self, script):
                for statement in script.split(";"):
                    if statement.strip():
                        self.connection.execute(statement)

        return PostgresConnection()
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    if os.environ.get("VERCEL") == "1" and not (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")):
        raise RuntimeError("Set DATABASE_URL to a persistent PostgreSQL database before deploying on Vercel.")
    if os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"):
        with connect_db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL, password_hash BYTEA NOT NULL,
                    password_salt BYTEA NOT NULL, created_at BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash BYTEA PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inventories (
                    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL DEFAULT '[]', updated_at BIGINT NOT NULL
                );
            """)
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
        return
    DATA_DIR.mkdir(exist_ok=True)
    with connect_db() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash BLOB NOT NULL,
                password_salt BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash BLOB PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inventories (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                payload TEXT NOT NULL DEFAULT '[]',
                updated_at INTEGER NOT NULL
            );
        """)
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)


class EdwaHandler(BaseHTTPRequestHandler):
    server_version = "Edwa/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def send_bytes(self, status: int, data: bytes, content_type: str,
                   extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, payload: object,
                  extra_headers: dict[str, str] | None = None) -> None:
        self.send_bytes(status, json.dumps(payload, separators=(",", ":")).encode(),
                        "application/json; charset=utf-8", extra_headers)

    def read_json(self) -> dict | list | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request."})
            return None
        if length <= 0 or length > MAX_BODY:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_BODY else HTTPStatus.BAD_REQUEST,
                           {"error": "Request is empty or too large."})
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})
            return None
        if not isinstance(body, (dict, list)):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request."})
            return None
        return body

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return False
        parsed = urlsplit(origin)
        return parsed.netloc.lower() == self.headers.get("Host", "").lower() and parsed.scheme in ("http", "https")

    def valid_host(self) -> bool:
        host_header = self.headers.get("Host", "")
        host = urlsplit(f"//{host_header}").hostname
        allowed_hosts = {"127.0.0.1", "localhost", "::1"}
        configured_hosts = os.environ.get("EDWA_ALLOWED_HOSTS", os.environ.get("FORMA_ALLOWED_HOSTS", ""))
        allowed_hosts.update(part.strip().lower() for part in configured_hosts.split(",") if part.strip())
        if os.environ.get("VERCEL") == "1":
            allowed_hosts.add((host or "").lower())
        return host in allowed_hosts

    def get_session(self) -> sqlite3.Row | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie[SESSION_COOKIE].value
        except (KeyError, TypeError):
            return None
        token_hash = hashlib.sha256(token.encode()).digest()
        with connect_db() as db:
            return db.execute("""SELECT users.id, users.email, users.display_name
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (token_hash, int(time.time()))).fetchone()

    def require_same_origin(self) -> bool:
        if self.same_origin():
            return True
        self.send_json(HTTPStatus.FORBIDDEN, {"error": "Request origin could not be verified."})
        return False

    def require_session(self) -> sqlite3.Row | None:
        user = self.get_session()
        if not user:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Please sign in to continue."})
        return user

    def set_session(self, user_id: int) -> None:
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + SESSION_TTL
        with connect_db() as db:
            db.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                       (hashlib.sha256(token.encode()).digest(), user_id, expires_at))
        secure_cookie = os.environ.get("EDWA_SECURE_COOKIE", os.environ.get("FORMA_SECURE_COOKIE", "0"))
        if os.environ.get("VERCEL") == "1":
            secure_cookie = "1"
        secure = "; Secure" if getattr(self.connection, "cipher", None) or secure_cookie == "1" else ""
        cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}{secure}"
        self._session_header = cookie

    def clear_session(self) -> None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie[SESSION_COOKIE].value
        except (KeyError, TypeError):
            token = ""
        if token:
            with connect_db() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?",
                           (hashlib.sha256(token.encode()).digest(),))
        self._session_header = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

    def session_headers(self) -> dict[str, str]:
        return {"Set-Cookie": self._session_header} if hasattr(self, "_session_header") else {}

    def request_limited(self) -> bool:
        now = time.time()
        address = self.client_address[0]
        recent = [stamp for stamp in LOGIN_ATTEMPTS.get(address, []) if now - stamp < 60]
        recent.append(now)
        LOGIN_ATTEMPTS[address] = recent
        if len(recent) > 10:
            self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Too many attempts. Please wait a minute and try again."},
                           {"Retry-After": "60"})
            return True
        return False

    def do_GET(self) -> None:
        if not self.valid_host():
            self.send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "This server only accepts local requests."})
            return
        path = unquote(urlsplit(self.path).path)
        if path == "/api/session":
            user = self.get_session()
            self.send_json(HTTPStatus.OK, {"user": {"email": user["email"], "name": user["display_name"]} if user else None})
            return
        if path == "/api/inventory":
            user = self.require_session()
            if not user:
                return
            with connect_db() as db:
                row = db.execute("SELECT payload FROM inventories WHERE user_id = ?", (user["id"],)).fetchone()
            self.send_json(HTTPStatus.OK, {"products": json.loads(row["payload"]) if row else [],
                                           "currency": self.get_currency(user["id"])})
            return
        if path not in ALLOWED_STATIC:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        target = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        try:
            data = target.read_bytes()
        except OSError:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript"
        self.send_bytes(HTTPStatus.OK, data, f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type in ("application/javascript", "text/javascript") else content_type)

    def get_currency(self, user_id: int) -> str:
        with connect_db() as db:
            row = db.execute("SELECT payload FROM inventories WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return "USD"
        try:
            parsed = json.loads(row["payload"])
            return parsed.get("currency", "USD") if isinstance(parsed, dict) else "USD"
        except (json.JSONDecodeError, AttributeError):
            return "USD"

    def do_POST(self) -> None:
        if not self.valid_host():
            self.send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "This server only accepts local requests."})
            return
        path = urlsplit(self.path).path
        if path in ("/api/register", "/api/login", "/api/logout", "/api/inventory") and not self.require_same_origin():
            return
        if path in ("/api/register", "/api/login") and self.request_limited():
            return
        if path == "/api/register":
            self.register()
        elif path == "/api/login":
            self.login()
        elif path == "/api/logout":
            if self.read_json() is None:
                return
            self.clear_session()
            self.send_json(HTTPStatus.OK, {"ok": True}, self.session_headers())
        elif path == "/api/inventory":
            self.save_inventory()
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def register(self) -> None:
        body = self.read_json()
        if not isinstance(body, dict):
            return
        name = str(body.get("name", "")).strip()[:60]
        email = str(body.get("email", "")).strip().lower()[:254]
        password = body.get("password", "")
        if not name or len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not isinstance(password, str) or len(password) < 10 or len(password) > 256:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Enter your name, a valid email, and a password with at least 10 characters."})
            return
        salt = secrets.token_bytes(16)
        digest = password_hash(password, salt)
        try:
            with connect_db() as db:
                insert_user = "INSERT INTO users (email, display_name, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)"
                if os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"):
                    cursor = db.execute(insert_user + " RETURNING id", (email, name, digest, salt, int(time.time())))
                    user_id = cursor.fetchone()["id"]
                else:
                    cursor = db.execute(insert_user, (email, name, digest, salt, int(time.time())))
                    user_id = cursor.lastrowid
                db.execute("INSERT INTO inventories (user_id, payload, updated_at) VALUES (?, ?, ?)",
                           (user_id, json.dumps({"products": [], "currency": "USD"}), int(time.time())))
        except Exception as error:
            if not isinstance(error, sqlite3.IntegrityError) and error.__class__.__name__ != "UniqueViolation":
                raise
            self.send_json(HTTPStatus.CONFLICT, {"error": "An account with that email already exists. Try signing in."})
            return
        self.set_session(user_id)
        self.send_json(HTTPStatus.CREATED, {"user": {"email": email, "name": name}}, self.session_headers())

    def login(self) -> None:
        body = self.read_json()
        if not isinstance(body, dict):
            return
        email = str(body.get("email", "")).strip().lower()[:254]
        password = body.get("password", "")
        if not isinstance(password, str) or len(password) > 256:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Email or password is incorrect."})
            return
        with connect_db() as db:
            user = db.execute("SELECT id, email, display_name, password_hash, password_salt FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not hmac.compare_digest(password_hash(password, user["password_salt"]), user["password_hash"]):
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Email or password is incorrect."})
            return
        self.set_session(user["id"])
        self.send_json(HTTPStatus.OK, {"user": {"email": user["email"], "name": user["display_name"]}}, self.session_headers())

    def save_inventory(self) -> None:
        user = self.require_session()
        if not user:
            return
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("products"), list):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid inventory."})
            return
        products = body["products"]
        if len(products) > 5000:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Inventory contains too many products."})
            return
        for item in products:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A product entry is invalid."})
                return
            if not isinstance(item.get("price"), (int, float)) or item["price"] <= 0 or not isinstance(item.get("quantity"), int) or item["quantity"] < 0:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A product price or quantity is invalid."})
                return
        currency = body.get("currency", "USD")
        if currency not in {"USD", "EUR", "GBP", "NGN", "GHS", "ZAR"}:
            currency = "USD"
        payload = json.dumps({"products": products, "currency": currency}, separators=(",", ":"), ensure_ascii=False)
        if len(payload.encode("utf-8")) > MAX_BODY:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Inventory is too large to save."})
            return
        with connect_db() as db:
            db.execute("INSERT INTO inventories (user_id, payload, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
                       (user["id"], payload, int(time.time())))
        self.send_json(HTTPStatus.OK, {"ok": True})

    def do_HEAD(self) -> None:
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})


# Vercel also discovers Python files at the project root as function entries.
# Export the existing HTTP handler so that discovery succeeds for server.py.
handler = EdwaHandler


def main() -> None:
    initialize_db()
    host = os.environ.get("EDWA_HOST", os.environ.get("FORMA_HOST", "127.0.0.1"))
    port = int(os.environ.get("EDWA_PORT", os.environ.get("FORMA_PORT", "8000")))
    server = ThreadingHTTPServer((host, port), EdwaHandler)
    print(f"Ɛdwa is ready at http://{host}:{port} — press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nƐdwa server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
