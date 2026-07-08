"""Alpha Vantage EOD market aggregator with file-backed caching."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import requests
from dotenv import load_dotenv

from core.config import DEMO_MODE

load_dotenv()

_MARKET_LOCK = threading.Lock()
_CACHE_FILENAME = ".market_cache.json"
_ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT_SECONDS = 2.5
_MARKET_TTL = timedelta(hours=12)
_COOLDOWN_DURATION = timedelta(minutes=15)

_DEMO_SYMBOLS: tuple[str, ...] = ("SPY", "AAPL", "MSFT")
_DEMO_BASE_PRICES: dict[str, float] = {
    "SPY": 520.0,
    "AAPL": 190.0,
    "MSFT": 420.0,
}

TickerStatus = Literal["live", "stale", "unavailable"]
MarketStatus = Literal[
    "live",
    "partial",
    "stale",
    "unavailable",
    "not_configured",
    "provider_unavailable",
]


def _cache_path() -> Path:
    return Path(__file__).resolve().parent / _CACHE_FILENAME


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime | None = None) -> str:
    current = dt or _now_utc()
    return current.astimezone(timezone.utc).isoformat()


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read_cache() -> dict[str, Any]:
    cache_file = _cache_path()
    if not cache_file.exists():
        return {"cooldown_until": None, "symbols": {}}

    try:
        with open(cache_file, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"cooldown_until": None, "symbols": {}}

    if not isinstance(payload, dict):
        return {"cooldown_until": None, "symbols": {}}

    symbols = payload.get("symbols")
    if not isinstance(symbols, dict):
        symbols = {}

    cooldown_until = payload.get("cooldown_until")
    if cooldown_until is not None and not isinstance(cooldown_until, str):
        cooldown_until = None

    return {"cooldown_until": cooldown_until, "symbols": symbols}


def _write_cache(cache: dict[str, Any]) -> None:
    cache_file = _cache_path()
    try:
        with open(cache_file, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, separators=(",", ":"))
    except (OSError, TypeError) as exc:
        sys.stderr.write(f"[MARKET][CACHE] {exc}\n")


def _parse_configured_symbols() -> list[str] | None:
    raw = os.environ.get("MARKET_SYMBOLS")
    if raw is None:
        return None

    symbols = [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]
    if not symbols:
        return None
    return symbols


def _get_api_key() -> str | None:
    raw = os.getenv("ALPHA_VANTAGE_API_KEY")
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _cooldown_state(cache: dict[str, Any]) -> tuple[bool, int]:
    until = _parse_iso(cache.get("cooldown_until"))
    if until is None:
        return False, 0

    remaining = until - _now_utc()
    if remaining.total_seconds() <= 0:
        return False, 0

    return True, max(0, int(remaining.total_seconds()))


def _set_cooldown(cache: dict[str, Any]) -> None:
    cache["cooldown_until"] = _iso_utc(_now_utc() + _COOLDOWN_DURATION)


def _is_entry_fresh(fetched_at: str | None, ttl: timedelta) -> bool:
    parsed = _parse_iso(fetched_at)
    if parsed is None:
        return False
    return _now_utc() - parsed <= ttl


def _alpha_vantage_get(params: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = requests.get(
            _ALPHA_VANTAGE_BASE,
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException as exc:
        return None, f"http_error:{exc}"
    except ValueError:
        return None, "invalid_json"

    if not isinstance(payload, dict):
        return None, "invalid_payload"

    if payload.get("Note") or payload.get("Information"):
        return None, "rate_limited"

    return payload, None


def _daily_close(series: dict[str, Any], date_key: str) -> float | None:
    day = series.get(date_key)
    if not isinstance(day, dict):
        return None
    return _parse_float(day.get("4. close"))


def _parse_daily_consolidated(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Derive EOD price, change metrics, and sparkline from TIME_SERIES_DAILY."""
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        return None

    dates = sorted(series.keys(), reverse=True)
    if len(dates) < 2:
        return None

    price_today = _daily_close(series, dates[0])
    price_yesterday = _daily_close(series, dates[1])
    if price_today is None or price_yesterday is None:
        return None

    change = price_today - price_yesterday
    change_percent = (change / price_yesterday) * 100.0 if price_yesterday else None

    sparkline: list[float] = []
    for date_key in dates[:7]:
        close = _daily_close(series, date_key)
        if close is not None:
            sparkline.append(close)

    if len(sparkline) < 2:
        return None

    return {
        "price": price_today,
        "change": change,
        "change_percent": change_percent,
        "sparkline": sparkline,
    }


def _ticker_from_cache(symbol: str, entry: dict[str, Any], *, status: TickerStatus) -> dict[str, Any]:
    sparkline = entry.get("sparkline")
    if not isinstance(sparkline, list):
        sparkline = []

    normalized_sparkline: list[float] = []
    for value in sparkline:
        parsed = _parse_float(value)
        if parsed is not None:
            normalized_sparkline.append(parsed)

    return {
        "symbol": symbol,
        "price": _parse_float(entry.get("price")),
        "change": _parse_float(entry.get("change")),
        "change_percent": _parse_float(entry.get("change_percent")),
        "status": status,
        "last_updated": entry.get("last_updated"),
        "sparkline": normalized_sparkline,
    }


def _has_cached_market_data(entry: dict[str, Any] | None) -> bool:
    if not entry:
        return False
    return any(
        entry.get(field) is not None
        for field in ("price", "change", "change_percent")
    )


def _resolve_global_status(ticker_statuses: list[TickerStatus]) -> MarketStatus:
    if not ticker_statuses:
        return "unavailable"

    if all(status == "live" for status in ticker_statuses):
        return "live"
    if any(status == "live" for status in ticker_statuses):
        return "partial"
    if any(status == "stale" for status in ticker_statuses):
        return "stale"
    return "unavailable"


def _build_response(
    *,
    status: MarketStatus,
    cooldown_active: bool,
    cooldown_remaining_seconds: int,
    tickers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "cooldown_active": cooldown_active,
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "tickers": tickers,
    }


def _is_simulation_mode() -> bool:
    """Return whether outbound market HTTP should be bypassed."""
    return DEMO_MODE or _get_api_key() is None


def _simulate_sparkline(current_price: float, *, seed_ts: float) -> list[float]:
    """Build seven daily closes trending smoothly toward the current mock price."""
    sparkline: list[float] = []
    for day_offset in range(0, 7):
        t = seed_ts - day_offset * 86_400
        drift = math.sin(t / 86_400.0) * current_price * 0.012
        retrace = current_price * (1.0 - day_offset * 0.004)
        point = round(retrace + drift, 2)
        sparkline.append(point)
    sparkline[0] = round(current_price, 2)
    return sparkline


def _simulate_ticker(symbol: str, now: datetime) -> dict[str, Any]:
    """Generate one dynamic demo ticker with sine-wave variation."""
    base = _DEMO_BASE_PRICES.get(symbol, 100.0)
    t = now.timestamp()

    wave_now = math.sin(t / 45.0) * base * 0.008
    price = round(base + wave_now, 2)

    wave_prior = math.sin((t - 86_400) / 45.0) * base * 0.008
    prior = round(base + wave_prior, 2)

    change = round(price - prior, 2)
    change_percent = round((change / prior) * 100.0, 2) if prior else 0.0
    now_iso = _iso_utc(now)

    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "change_percent": change_percent,
        "status": "live",
        "last_updated": now_iso,
        "sparkline": _simulate_sparkline(price, seed_ts=t),
    }


def _fetch_demo_market_data() -> dict[str, Any]:
    """Return high-fidelity simulated market snapshots without network IO."""
    now = _now_utc()
    tickers = [_simulate_ticker(symbol, now) for symbol in _DEMO_SYMBOLS]
    return _build_response(
        status="live",
        cooldown_active=False,
        cooldown_remaining_seconds=0,
        tickers=tickers,
    )


def fetch_market_data() -> dict[str, Any]:
    """Return EOD market snapshot with cache-first TIME_SERIES_DAILY aggregation."""
    if _is_simulation_mode():
        return _fetch_demo_market_data()

    symbols = _parse_configured_symbols()
    if symbols is None:
        return _build_response(
            status="not_configured",
            cooldown_active=False,
            cooldown_remaining_seconds=0,
            tickers=[],
        )

    api_key = _get_api_key()

    with _MARKET_LOCK:
        cache = _read_cache()
        cooldown_active, cooldown_remaining = _cooldown_state(cache)
        symbol_cache: dict[str, Any] = cache.setdefault("symbols", {})

        fetch_failed = False
        live_symbols: set[str] = set()

        if not cooldown_active:
            for symbol in symbols:
                entry = symbol_cache.get(symbol)
                if not isinstance(entry, dict):
                    entry = {}
                    symbol_cache[symbol] = entry

                market_fresh = _is_entry_fresh(entry.get("market_fetched_at"), _MARKET_TTL)

                if not market_fresh:
                    payload, error = _alpha_vantage_get(
                        {
                            "function": "TIME_SERIES_DAILY",
                            "symbol": symbol,
                            "apikey": api_key,
                        }
                    )
                    if error is not None:
                        fetch_failed = True
                        _set_cooldown(cache)
                        cooldown_active, cooldown_remaining = _cooldown_state(cache)
                        break

                    consolidated = _parse_daily_consolidated(payload or {})
                    if consolidated is None:
                        fetch_failed = True
                        _set_cooldown(cache)
                        cooldown_active, cooldown_remaining = _cooldown_state(cache)
                        break

                    now_iso = _iso_utc()
                    entry["price"] = consolidated["price"]
                    entry["change"] = consolidated["change"]
                    entry["change_percent"] = consolidated["change_percent"]
                    entry["sparkline"] = consolidated["sparkline"]
                    entry["last_updated"] = now_iso
                    entry["market_fetched_at"] = now_iso
                    live_symbols.add(symbol)

            _write_cache(cache)
        else:
            fetch_failed = True

        tickers = []
        ticker_statuses: list[TickerStatus] = []

        for symbol in symbols:
            entry = symbol_cache.get(symbol)
            if not isinstance(entry, dict):
                entry = {}

            market_fresh = _is_entry_fresh(entry.get("market_fetched_at"), _MARKET_TTL)

            if symbol in live_symbols or market_fresh:
                ticker_status: TickerStatus = "live"
            elif _has_cached_market_data(entry):
                ticker_status = "stale"
            else:
                ticker_status = "unavailable"

            tickers.append(_ticker_from_cache(symbol, entry, status=ticker_status))
            ticker_statuses.append(ticker_status)

        if fetch_failed and not any(status == "live" for status in ticker_statuses):
            global_status: MarketStatus = (
                "stale" if any(status == "stale" for status in ticker_statuses) else "unavailable"
            )
        else:
            global_status = _resolve_global_status(ticker_statuses)

        return _build_response(
            status=global_status,
            cooldown_active=cooldown_active,
            cooldown_remaining_seconds=cooldown_remaining,
            tickers=tickers,
        )


if __name__ == "__main__":
    snapshot = fetch_market_data()
    print(json.dumps(snapshot, indent=2))
