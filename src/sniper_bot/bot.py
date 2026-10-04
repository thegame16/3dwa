from __future__ import annotations

from dataclasses import dataclass, field
import time

from sniper_bot.config import BotConfig
from sniper_bot.execution import MT5ExecutionEngine
from sniper_bot.models import ClosedTrade, Position
from sniper_bot.mt5_client import MT5Connector
from sniper_bot.risk import RiskManager
from sniper_bot.strategy import SniperStrategy


@dataclass(slots=True)
class BotState:
    position: Position | None = None
    trades: list[ClosedTrade] = field(default_factory=list)
    skipped_signals: int = 0
    last_bar_ts: int | None = None


class SniperBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.strategy = SniperStrategy(config.strategy)
        self.risk = RiskManager(config.risk)
        self.connector = MT5Connector(config.mt5)
        self.execution = MT5ExecutionEngine(self.connector, config.mt5, config.risk)
        self.state = BotState()

    def run_forever(self) -> None:
        self.connector.initialize()
        self.connector.ensure_symbol(self.config.strategy.symbol)
        try:
            while True:
                self.run_once()
                time.sleep(self.config.mt5.poll_interval_seconds)
        finally:
            self._close_on_shutdown_if_needed()
            self.connector.shutdown()

    def run_once(self) -> BotState:
        tick = self.connector.get_latest_bar(self.config.strategy.symbol, self.config.strategy.timeframe)
        if tick is None or tick.ts == self.state.last_bar_ts:
            return self.state

        self.state.last_bar_ts = tick.ts
        self._process_tick(tick)
        return self.state

    def _process_tick(self, tick) -> None:
        position = self.state.position
        if position is not None:
            should_exit, reason = self.strategy.should_exit(tick, position)
            if should_exit:
                trade = self.execution.close_position(tick, position, reason)
                self.risk.register_trade(trade)
                self.state.trades.append(trade)
                self.state.position = None

        signal = self.strategy.on_tick(tick, self.state.position)
        if signal is None:
            return

        if signal.side.value == "short" and not self.config.mt5.allow_short:
            self.state.skipped_signals += 1
            return

        account = self.connector.account_snapshot()
        if not self.risk.allow_new_trade(account.equity):
            self.state.skipped_signals += 1
            return

        size_lots = self.execution.size_order(signal, self.risk.risk_budget_usd(account.equity))
        if size_lots <= 0:
            self.state.skipped_signals += 1
            return

        position, _ = self.execution.open_position(tick, signal, size_lots)
        self.state.position = position

    def _close_on_shutdown_if_needed(self) -> None:
        if self.config.mt5.close_on_shutdown and self.state.position is not None:
            dummy_tick = self.connector.get_latest_bar(self.config.strategy.symbol, self.config.strategy.timeframe)
            if dummy_tick is not None:
                trade = self.execution.close_position(dummy_tick, self.state.position, "shutdown")
                self.risk.register_trade(trade)
                self.state.trades.append(trade)
                self.state.position = None
