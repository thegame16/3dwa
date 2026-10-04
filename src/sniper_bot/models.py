from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(slots=True)
class MarketTick:
    ts: int
    symbol: str
    bid: float
    ask: float
    price: float
    high: float
    low: float
    close: float
    volume: float
    aggressive_buy_volume: float
    aggressive_sell_volume: float

    @property
    def imbalance(self) -> float:
        total = self.aggressive_buy_volume + self.aggressive_sell_volume
        if total <= 0:
            return 0.0
        return (self.aggressive_buy_volume - self.aggressive_sell_volume) / total

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)


@dataclass(slots=True)
class Signal:
    symbol: str
    side: Side
    entry_price: float
    stop_price: float
    take_profit_price: float
    reason: str


@dataclass(slots=True)
class Position:
    ticket: int
    symbol: str
    side: Side
    entry_price: float
    volume_lots: float
    stop_price: float
    take_profit_price: float
    opened_at_tick: int


@dataclass(slots=True)
class Fill:
    ticket: int
    side: Side
    price: float
    volume_lots: float
    tick_id: int


@dataclass(slots=True)
class ClosedTrade:
    ticket: int
    side: Side
    symbol: str
    entry_price: float
    exit_price: float
    volume_lots: float
    pnl_usd: float
    entry_tick: int
    exit_tick: int
    reason: str
