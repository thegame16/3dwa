import unittest

from sniper_bot.config import BotConfig
from sniper_bot.execution import SymbolSpec, normalize_volume
from sniper_bot.models import MarketTick
from sniper_bot.strategy import SniperStrategy


class StrategyTest(unittest.TestCase):
    def test_breakout_generates_long_signal(self) -> None:
        strategy = SniperStrategy(BotConfig.defaults().strategy)
        ticks = [
            MarketTick(ts=1, symbol="BTCUSD", bid=65000, ask=65002, price=65001, high=65005, low=64980, close=64995, volume=10, aggressive_buy_volume=4, aggressive_sell_volume=6),
            MarketTick(ts=2, symbol="BTCUSD", bid=65003, ask=65005, price=65004, high=65010, low=64990, close=65000, volume=11, aggressive_buy_volume=5, aggressive_sell_volume=6),
            MarketTick(ts=3, symbol="BTCUSD", bid=65006, ask=65008, price=65007, high=65015, low=64995, close=65002, volume=12, aggressive_buy_volume=5, aggressive_sell_volume=7),
            MarketTick(ts=4, symbol="BTCUSD", bid=65008, ask=65010, price=65009, high=65018, low=64998, close=65006, volume=12, aggressive_buy_volume=6, aggressive_sell_volume=6),
            MarketTick(ts=5, symbol="BTCUSD", bid=65010, ask=65012, price=65011, high=65020, low=65000, close=65010, volume=13, aggressive_buy_volume=7, aggressive_sell_volume=6),
            MarketTick(ts=6, symbol="BTCUSD", bid=65014, ask=65016, price=65015, high=65025, low=65003, close=65018, volume=13, aggressive_buy_volume=8, aggressive_sell_volume=5),
            MarketTick(ts=7, symbol="BTCUSD", bid=65018, ask=65020, price=65019, high=65028, low=65006, close=65024, volume=14, aggressive_buy_volume=9, aggressive_sell_volume=5),
            MarketTick(ts=8, symbol="BTCUSD", bid=65058, ask=65060, price=65059, high=65070, low=65015, close=65068, volume=16, aggressive_buy_volume=13, aggressive_sell_volume=3),
        ]

        signal = None
        for tick in ticks:
            signal = strategy.on_tick(tick, None)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "BTCUSD")
        self.assertEqual(signal.side.value, "long")

    def test_volume_normalization_respects_symbol_step(self) -> None:
        spec = SymbolSpec(
            point=0.01,
            volume_min=0.01,
            volume_max=5.0,
            volume_step=0.01,
            tick_value=1.0,
            tick_size=0.01,
        )
        self.assertEqual(normalize_volume(0.237, spec, 2.0), 0.24)
        self.assertEqual(normalize_volume(9.0, spec, 2.0), 2.0)
        self.assertEqual(normalize_volume(0.001, spec, 2.0), 0.0)


if __name__ == "__main__":
    unittest.main()
