from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(slots=True)
class StrategyConfig:
    symbol: str = "BTCUSD"
    timeframe: str = "M1"
    breakout_lookback: int = 8
    momentum_threshold: float = 10.0
    imbalance_threshold: float = 0.05
    take_profit_multiple: float = 1.6
    stop_loss_multiple: float = 1.0
    max_hold_bars: int = 6


@dataclass(slots=True)
class RiskConfig:
    fallback_equity_usd: float = 10_000.0
    risk_per_trade_fraction: float = 0.005
    max_volume_lots: float = 2.0
    max_daily_loss_fraction: float = 0.03
    max_consecutive_losses: int = 3
    use_live_equity: bool = True


@dataclass(slots=True)
class MT5Config:
    path: str | None = None
    login: int | None = None
    password: str | None = None
    server: str | None = None
    magic: int = 22042026
    deviation_points: int = 20
    poll_interval_seconds: float = 0.5
    reconnect_delay_seconds: float = 5.0
    allow_short: bool = True
    close_on_shutdown: bool = False
    comment: str = "BTCUSD Sniper V2"


@dataclass(slots=True)
class BotConfig:
    strategy: StrategyConfig
    risk: RiskConfig
    mt5: MT5Config

    @classmethod
    def defaults(cls) -> "BotConfig":
        return cls(
            strategy=StrategyConfig(),
            risk=RiskConfig(),
            mt5=MT5Config(),
        )


def _merge_dataclass(dataclass_type, payload: dict) -> object:
    defaults = dataclass_type()
    for key, value in payload.items():
        if not hasattr(defaults, key):
            raise ValueError(f"Unknown config key '{key}' for {dataclass_type.__name__}")
        setattr(defaults, key, value)
    return defaults


def load_config(path: str | Path | None = None) -> BotConfig:
    if path is None:
        return BotConfig.defaults()

    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    strategy = _merge_dataclass(StrategyConfig, data.get("strategy", {}))
    risk = _merge_dataclass(RiskConfig, data.get("risk", {}))
    mt5 = _merge_dataclass(MT5Config, data.get("mt5", {}))
    return BotConfig(strategy=strategy, risk=risk, mt5=mt5)
