from __future__ import annotations

from sniper_bot.config import RiskConfig
from sniper_bot.models import ClosedTrade


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.realized_pnl_usd = 0.0
        self.consecutive_losses = 0

    def equity_for_sizing(self, live_equity: float | None) -> float:
        if self.config.use_live_equity and live_equity and live_equity > 0:
            return live_equity
        return self.config.fallback_equity_usd

    def risk_budget_usd(self, live_equity: float | None) -> float:
        return self.equity_for_sizing(live_equity) * self.config.risk_per_trade_fraction

    def allow_new_trade(self, live_equity: float | None) -> bool:
        baseline = self.equity_for_sizing(live_equity)
        if self.realized_pnl_usd <= -(baseline * self.config.max_daily_loss_fraction):
            return False
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            return False
        return True

    def register_trade(self, trade: ClosedTrade) -> None:
        self.realized_pnl_usd += trade.pnl_usd
        if trade.pnl_usd < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
