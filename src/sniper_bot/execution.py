from __future__ import annotations

from dataclasses import dataclass

from sniper_bot.config import MT5Config, RiskConfig
from sniper_bot.models import ClosedTrade, Fill, MarketTick, Position, Side, Signal


@dataclass(slots=True)
class SymbolSpec:
    point: float
    volume_min: float
    volume_max: float
    volume_step: float
    tick_value: float
    tick_size: float


def normalize_volume(raw_volume: float, spec: SymbolSpec, max_volume_lots: float) -> float:
    capped = min(raw_volume, max_volume_lots, spec.volume_max)
    if capped < spec.volume_min:
        return 0.0
    steps = round(capped / spec.volume_step)
    normalized = steps * spec.volume_step
    return round(max(spec.volume_min, min(normalized, max_volume_lots, spec.volume_max)), 8)


class MT5ExecutionEngine:
    def __init__(self, connector, mt5_config: MT5Config, risk_config: RiskConfig) -> None:
        self.connector = connector
        self.mt5_config = mt5_config
        self.risk_config = risk_config

    def size_order(self, signal: Signal, risk_budget_usd: float) -> float:
        loss_per_lot = self.connector.loss_per_lot(signal)
        if loss_per_lot <= 0:
            return 0.0
        raw_volume = risk_budget_usd / loss_per_lot
        return normalize_volume(raw_volume, self.connector.symbol_spec(signal.symbol), self.risk_config.max_volume_lots)

    def open_position(self, tick: MarketTick, signal: Signal, volume_lots: float) -> tuple[Position, Fill]:
        order = self.connector.send_entry_order(signal, volume_lots)
        position = Position(
            ticket=order["ticket"],
            symbol=signal.symbol,
            side=signal.side,
            entry_price=order["price"],
            volume_lots=order["volume"],
            stop_price=signal.stop_price,
            take_profit_price=signal.take_profit_price,
            opened_at_tick=tick.ts,
        )
        fill = Fill(
            ticket=order["ticket"],
            side=signal.side,
            price=order["price"],
            volume_lots=order["volume"],
            tick_id=tick.ts,
        )
        return position, fill

    def close_position(self, tick: MarketTick, position: Position, reason: str) -> ClosedTrade:
        result = self.connector.close_position(position)
        return ClosedTrade(
            ticket=position.ticket,
            side=position.side,
            symbol=position.symbol,
            entry_price=position.entry_price,
            exit_price=result["price"],
            volume_lots=result["volume"],
            pnl_usd=result["pnl_usd"],
            entry_tick=position.opened_at_tick,
            exit_tick=tick.ts,
            reason=reason,
        )
