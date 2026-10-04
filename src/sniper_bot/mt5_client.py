from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from sniper_bot.config import MT5Config
from sniper_bot.execution import SymbolSpec
from sniper_bot.models import MarketTick, Position, Side, Signal

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M2": "TIMEFRAME_M2",
    "M3": "TIMEFRAME_M3",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
}


@dataclass(slots=True)
class AccountSnapshot:
    equity: float
    balance: float
    leverage: int


class MT5Connector:
    def __init__(self, config: MT5Config) -> None:
        self.config = config
        self._last_error: tuple[int, str] | None = None

    def initialize(self) -> None:
        self._require_mt5()
        kwargs: dict[str, Any] = {}
        if self.config.path:
            kwargs["path"] = self.config.path
        if self.config.login:
            kwargs["login"] = self.config.login
        if self.config.password:
            kwargs["password"] = self.config.password
        if self.config.server:
            kwargs["server"] = self.config.server

        if not mt5.initialize(**kwargs):
            self._raise_last_error("Failed to initialize MetaTrader 5")

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    def ensure_symbol(self, symbol: str) -> None:
        self._require_mt5()
        if not mt5.symbol_select(symbol, True):
            self._raise_last_error(f"Unable to subscribe symbol {symbol}")

    def account_snapshot(self) -> AccountSnapshot:
        info = mt5.account_info()
        if info is None:
            self._raise_last_error("Unable to fetch MT5 account info")
        return AccountSnapshot(
            equity=float(info.equity),
            balance=float(info.balance),
            leverage=int(info.leverage),
        )

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        info = mt5.symbol_info(symbol)
        if info is None:
            self._raise_last_error(f"Unable to load symbol info for {symbol}")
        return SymbolSpec(
            point=float(info.point),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            tick_value=float(info.trade_tick_value or 0.0),
            tick_size=float(info.trade_tick_size or info.point or 0.0),
        )

    def get_latest_bar(self, symbol: str, timeframe_name: str) -> MarketTick | None:
        timeframe = self._resolve_timeframe(timeframe_name)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, 2)
        tick = mt5.symbol_info_tick(symbol)
        if rates is None or len(rates) == 0 or tick is None:
            self._last_error = mt5.last_error()
            return None

        bar = rates[-1]
        high = float(bar["high"])
        low = float(bar["low"])
        open_price = float(bar["open"])
        close = float(bar["close"])
        tick_volume = float(bar["tick_volume"])
        buy_pressure = tick_volume * self._close_location_ratio(close, low, high)
        sell_pressure = max(0.0, tick_volume - buy_pressure)
        return MarketTick(
            ts=int(bar["time"]),
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            price=float((tick.bid + tick.ask) / 2),
            high=high,
            low=low,
            close=close,
            volume=tick_volume,
            aggressive_buy_volume=max(0.0, buy_pressure + max(close - open_price, 0.0)),
            aggressive_sell_volume=max(0.0, sell_pressure + max(open_price - close, 0.0)),
        )

    def loss_per_lot(self, signal: Signal) -> float:
        order_type = mt5.ORDER_TYPE_BUY if signal.side is Side.LONG else mt5.ORDER_TYPE_SELL
        pnl = mt5.order_calc_profit(order_type, signal.symbol, 1.0, signal.entry_price, signal.stop_price)
        if pnl is None:
            self._last_error = mt5.last_error()
            return 0.0
        return abs(float(pnl))

    def send_entry_order(self, signal: Signal, volume_lots: float) -> dict[str, float | int]:
        order_type = mt5.ORDER_TYPE_BUY if signal.side is Side.LONG else mt5.ORDER_TYPE_SELL
        price = signal.entry_price
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal.symbol,
            "volume": volume_lots,
            "type": order_type,
            "price": price,
            "sl": signal.stop_price,
            "tp": signal.take_profit_price,
            "deviation": self.config.deviation_points,
            "magic": self.config.magic,
            "comment": self.config.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            self._last_error = mt5.last_error()
            raise RuntimeError(f"MT5 entry order failed retcode={getattr(result, 'retcode', 'none')}")

        return {
            "ticket": int(result.order or result.deal),
            "price": float(result.price),
            "volume": float(result.volume),
        }

    def close_position(self, position: Position) -> dict[str, float]:
        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            self._raise_last_error(f"Unable to fetch tick for {position.symbol} while closing")

        close_side = mt5.ORDER_TYPE_SELL if position.side is Side.LONG else mt5.ORDER_TYPE_BUY
        close_price = float(tick.bid if position.side is Side.LONG else tick.ask)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "position": position.ticket,
            "volume": position.volume_lots,
            "type": close_side,
            "price": close_price,
            "deviation": self.config.deviation_points,
            "magic": self.config.magic,
            "comment": f"{self.config.comment} exit",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            self._last_error = mt5.last_error()
            raise RuntimeError(f"MT5 close order failed retcode={getattr(result, 'retcode', 'none')}")

        pnl = self._estimate_trade_pnl(position, close_price)
        return {
            "price": close_price,
            "volume": float(position.volume_lots),
            "pnl_usd": pnl,
        }

    def sleep_until_retry(self) -> None:
        time.sleep(self.config.reconnect_delay_seconds)

    def _resolve_timeframe(self, timeframe_name: str) -> int:
        self._require_mt5()
        attr_name = TIMEFRAME_MAP.get(timeframe_name.upper())
        if attr_name is None or not hasattr(mt5, attr_name):
            raise ValueError(f"Unsupported MT5 timeframe '{timeframe_name}'")
        return getattr(mt5, attr_name)

    def _estimate_trade_pnl(self, position: Position, close_price: float) -> float:
        order_type = mt5.ORDER_TYPE_BUY if position.side is Side.LONG else mt5.ORDER_TYPE_SELL
        pnl = mt5.order_calc_profit(order_type, position.symbol, position.volume_lots, position.entry_price, close_price)
        if pnl is None:
            self._last_error = mt5.last_error()
            return 0.0
        return float(pnl)

    def _close_location_ratio(self, close: float, low: float, high: float) -> float:
        if high <= low:
            return 0.5
        return min(1.0, max(0.0, (close - low) / (high - low)))

    def _require_mt5(self) -> None:
        if mt5 is None:
            raise RuntimeError(
                "MetaTrader5 package is not installed. Install it in the target Python environment before running live."
            )

    def _raise_last_error(self, message: str) -> None:
        error = mt5.last_error() if mt5 is not None else (-1, "MetaTrader5 package unavailable")
        raise RuntimeError(f"{message}: {error}")
