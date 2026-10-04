from __future__ import annotations

import argparse

from sniper_bot.bot import SniperBot
from sniper_bot.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BTCUSD Sniper V2 bot on MetaTrader 5.")
    parser.add_argument("--config", help="Path to a TOML config file.", default=None)
    parser.add_argument("--once", action="store_true", help="Process at most one fresh completed bar and exit.")
    args = parser.parse_args()

    config = load_config(args.config)
    bot = SniperBot(config)

    if args.once:
        bot.connector.initialize()
        bot.connector.ensure_symbol(config.strategy.symbol)
        try:
            state = bot.run_once()
        finally:
            bot.connector.shutdown()
        print("MT5 sniper cycle complete")
        print(f"last_bar_ts={state.last_bar_ts} open_position={state.position is not None} skipped_signals={state.skipped_signals}")
        return

    bot.run_forever()


if __name__ == "__main__":
    main()
