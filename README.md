# Ɛdwa — Store Inventory

A minimalist inventory app with private accounts, product photos, stock tracking, and sales totals. Product and account data are saved in a local SQLite database, separated by account.

## Start Ɛdwa

Requires Python 3.11 or newer. No Python packages are needed for the inventory web app.

```powershell
python server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), then choose **Create an account**. The server binds to `127.0.0.1` by default and stores account/inventory data in `data/forma.sqlite3`. Keep the `data` directory private and back it up with the store data.

The built-in server is intended for local use. For remote access, deploy behind HTTPS with a production-grade web server and database. Configure `EDWA_ALLOWED_HOSTS` to include the public hostname and `EDWA_SECURE_COOKIE=1` when TLS ends at a reverse proxy. Account email verification, password recovery, and multi-factor authentication are not included. Use a unique password. The server applies per-IP login attempt throttling; sessions use HttpOnly, SameSite cookies and expire after 14 days.

## Deploy to Vercel

The inventory interface is served as static files, and `api/[...path].py` routes the account and inventory endpoints to Vercel's Python runtime. Vercel deployments must use a persistent PostgreSQL database because function filesystems do not provide durable SQLite storage.

1. Import this repository into Vercel and deploy it with the project root set to this directory. The Python API runtime is detected from `api/[...path].py` and `pyproject.toml`.
2. Add a PostgreSQL database through a Vercel Marketplace integration such as Neon or Supabase.
3. Set `DATABASE_URL` in the Vercel project's Production and Preview environments to the database connection string provided by that integration.
4. Redeploy after setting the environment variable. The API creates its tables on first request.

Local runs continue to use `data/forma.sqlite3`. Do not use the SQLite fallback for a Vercel deployment; without `DATABASE_URL`, data would be stored on ephemeral function storage and can disappear. The separate MetaTrader bot is not deployable as a Vercel function because it requires a continuously running process and a local MT5 terminal.

## Inventory features

- Add products with a photo, name, unit price, initial quantity, and optional category.
- Record sales by quantity. Stock decreases automatically and sales totals update.
- Restock items, search products, sort the list, and filter low or out of stock items.
- View inventory value, items on hand, sales recorded, and items that need attention.
- Choose a display currency from preferences. This changes the display format and does not convert existing amounts.
- Hear a soft rising tone when stock is added and a lower falling tone when it is deducted; use the speaker control to mute or re-enable sounds.
- Product data and compressed product photos are scoped to the signed-in account.

The original `src/sniper_bot` Python package is the separate MetaTrader trading bot. The inventory web app does not connect to it. Existing inventory saved in an earlier browser session is migrated to the first account created on that browser.

## BTCUSD Sniper V2 for MT5

The separate Python project connects to a local MT5 terminal, subscribes to `BTCUSD`, polls completed bars, generates breakout entries, sizes positions using account equity and stop distance, sends market orders with stop loss and take profit, and tracks realized PnL and loss limits in-process.

### Setup

1. Install the `MetaTrader5` Python package in the Python environment you will run.
2. Log into your broker in the MT5 desktop terminal.
3. Copy `config.sample.toml` and replace its login, password, server, and terminal path values.
4. Enable algorithmic trading in MT5 and confirm `BTCUSD` is available from your broker.

Run it with:

```powershell
$env:PYTHONPATH='src'
python -m sniper_bot.main --config config.sample.toml
```

Use `--once` to process one fresh completed bar and exit. Some brokers use symbol names like `BTCUSD.a` or `BTCUSDm`. Position sizing depends on broker symbol contract metadata and `order_calc_profit`. The bot tracks one open position at a time in-process and does not recover existing MT5 positions automatically after restart. Review the config and risk behavior before use.
