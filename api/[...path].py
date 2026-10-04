"""Vercel catch-all API function for the existing inventory endpoints."""

from server import EdwaHandler, initialize_db


class handler(EdwaHandler):
    """Run the shared API handler as a Vercel Python Function."""

    def do_GET(self):
        initialize_db()
        super().do_GET()

    def do_POST(self):
        initialize_db()
        super().do_POST()
