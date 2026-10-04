from __future__ import annotations

from collections import deque

from sniper_bot.config import StrategyConfig
from sniper_bot.models import MarketTick, Position, Side, Signal


class SniperStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config
        self.window: deque[MarketTick] = deque(maxlen=max(config.breakout_lookback, 2))

    def on_tick(self, tick: MarketTick, position: Position | None) -> Signal | None:
        self.window.append(tick)
        if position is not None or len(self.window) < self.window.maxlen:
            return None

        recent = list(self.window)
        current = recent[-1]
        history = recent[:-1]
        prev_high = max(item.high for item in history)
        prev_low = min(item.low for item in history)
        momentum = self._momentum_score(recent)

        if (
            current.close > prev_high
            and momentum >= self.config.momentum_threshold
            and current.imbalance >= self.config.imbalance_threshold
        ):
            return self._build_signal(current, Side.LONG, momentum, prev_low)

        if (
            current.close < prev_low
            and momentum <= -self.config.momentum_threshold
            and current.imbalance <= -self.config.imbalance_threshold
        ):
            return self._build_signal(current, Side.SHORT, momentum, prev_high)

        return None

    def should_exit(self, tick: MarketTick, position: Position) -> tuple[bool, str]:
        if position.side is Side.LONG:
            if tick.low <= position.stop_price:
                return True, "stop_loss"
            if tick.high >= position.take_profit_price:
                return True, "take_profit"
        else:
            if tick.high >= position.stop_price:
                return True, "stop_loss"
            if tick.low <= position.take_profit_price:
                return True, "take_profit"

        if tick.ts - position.opened_at_tick >= self.config.max_hold_bars:
            return True, "time_exit"

        return False, ""

    def _build_signal(
        self,
        tick: MarketTick,
        side: Side,
        momentum: float,
        anchor_price: float,
    ) -> Signal:
        distance = abs(tick.close - anchor_price)
        stop_distance = max(distance * 0.35, tick.close * 0.0012) * self.config.stop_loss_multiple
        take_profit_distance = stop_distance * self.config.take_profit_multiple

        if side is Side.LONG:
            entry_price = tick.ask
            stop_price = tick.close - stop_distance
            take_profit_price = tick.close + take_profit_distance
        else:
            entry_price = tick.bid
            stop_price = tick.close + stop_distance
            take_profit_price = tick.close - take_profit_distance

        return Signal(
            symbol=tick.symbol,
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            reason=f"breakout momentum={momentum:.1f} imbalance={tick.imbalance:.2f}",
        )

    def _momentum_score(self, ticks: list[MarketTick]) -> float:
        start = ticks[0].close
        end = ticks[-1].close
        if start == 0:
            return 0.0
        return ((end - start) / start) * 10_000
