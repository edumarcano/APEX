"""Alpha Vantage EOD market collection and cache-backed display data."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from clients.http_sessions import get_connector_http_session
from core.config import DEMO_MODE
from core.connectors.models import ConnectorResult, utc_now_iso
from core.settings import get_settings_store

load_dotenv()

_MARKET_LOCK = threading.Lock()
_CACHE_FILENAME = ".market_cache.json"
_CACHE_VERSION = 2
_ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT_SECONDS = 2.5
_MARKET_TTL = timedelta(hours=12)
_COOLDOWN_DURATION = timedelta(minutes=15)
_SYMBOL_COOLDOWN_DURATION = timedelta(minutes=15)
_DISPLAY_HISTORY_LENGTH = 20
_MAX_HISTORY_LENGTH = 100

_DEMO_SYMBOLS: tuple[str, ...] = ("SPY", "AAPL", "MSFT")
_DEMO_BASE_PRICES: dict[str, float] = {"SPY": 520.0, "AAPL": 190.0, "MSFT": 420.0}


def _cache_path() -> Path:
    return Path(__file__).resolve().parent / _CACHE_FILENAME


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime | None = None) -> str:
    return (dt or _now_utc()).astimezone(timezone.utc).isoformat()


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _parse_float(value: object) -> float | None:
    try:
        parsed = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _empty_cache() -> dict[str, Any]:
    return {"version": _CACHE_VERSION, "cooldown_until": None, "collection_revision": 0, "symbols": {}}


def _read_cache() -> dict[str, Any]:
    try:
        with _cache_path().open(encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(raw, dict):
        return _empty_cache()
    symbols = raw.get("symbols") if isinstance(raw.get("symbols"), dict) else {}
    revision = raw.get("collection_revision")
    return {
        "version": _CACHE_VERSION,
        "cooldown_until": raw.get("cooldown_until") if isinstance(raw.get("cooldown_until"), str) else None,
        "collection_revision": revision if isinstance(revision, int) and revision >= 0 else 0,
        "symbols": symbols,
    }


def _write_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(cache, handle, separators=(",", ":"))
        temporary.replace(path)
    except (OSError, TypeError) as exc:
        sys.stderr.write(f"[MARKET][CACHE] {exc}\n")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _configured_symbols() -> list[str] | None:
    symbols = list(get_settings_store().get_snapshot().market.symbols)
    return symbols or None


def _market_enabled() -> bool:
    return bool(get_settings_store().get_snapshot().features.market)


def _get_api_key() -> str | None:
    raw = os.getenv("ALPHA_VANTAGE_API_KEY")
    return raw.strip() if raw and raw.strip() else None


def _is_fresh(raw: object, ttl: timedelta) -> bool:
    parsed = _parse_iso(raw)
    return parsed is not None and _now_utc() - parsed <= ttl


def _cooldown_remaining(raw: object) -> int:
    until = _parse_iso(raw)
    if until is None:
        return 0
    return max(0, int((until - _now_utc()).total_seconds()))


def _alpha_vantage_get(params: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        session = get_connector_http_session("market")
        response = (session.get if session is not None else requests.get)(
            _ALPHA_VANTAGE_BASE, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException:
        return None, "http_error"
    except ValueError:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_payload"
    if payload.get("Note") or payload.get("Information"):
        return None, "rate_limited"
    return payload, None


def _parse_daily_history(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict):
        return None
    history: list[dict[str, Any]] = []
    for raw_date, raw_bar in series.items():
        if not isinstance(raw_date, str) or not isinstance(raw_bar, dict):
            continue
        try:
            date.fromisoformat(raw_date)
        except ValueError:
            continue
        opening = _parse_float(raw_bar.get("1. open"))
        high = _parse_float(raw_bar.get("2. high"))
        low = _parse_float(raw_bar.get("3. low"))
        close = _parse_float(raw_bar.get("4. close"))
        volume = _parse_float(raw_bar.get("5. volume"))
        if None in {opening, high, low, close, volume}:
            continue
        assert opening is not None and high is not None and low is not None and close is not None and volume is not None
        if low > high or high < max(opening, close) or low > min(opening, close) or volume < 0:
            continue
        history.append({"date": raw_date, "open": opening, "high": high, "low": low, "close": close, "volume": volume})
    history.sort(key=lambda bar: bar["date"])
    return history[-_MAX_HISTORY_LENGTH:] if len(history) >= 2 else None


def _usable_entry(entry: dict[str, Any]) -> bool:
    history = entry.get("history")
    if isinstance(history, list) and len(history) >= 2:
        return True
    return any(_parse_float(entry.get(field)) is not None for field in ("price", "change", "change_percent"))


def _ticker_from_entry(symbol: str, entry: dict[str, Any], *, fetched_live: bool = False) -> dict[str, Any]:
    history = entry.get("history") if isinstance(entry.get("history"), list) else []
    bars = [bar for bar in history if isinstance(bar, dict)][-_DISPLAY_HISTORY_LENGTH:]
    close = _parse_float(bars[-1].get("close")) if bars else _parse_float(entry.get("price"))
    previous = _parse_float(bars[-2].get("close")) if len(bars) >= 2 else None
    change = close - previous if close is not None and previous is not None else _parse_float(entry.get("change"))
    change_percent = change / previous * 100 if change is not None and previous else _parse_float(entry.get("change_percent"))
    status, freshness = "unavailable", "none"
    if len(bars) >= 2:
        status, freshness = "healthy", ("live" if fetched_live else "fresh_cache")
        if not _is_fresh(entry.get("market_fetched_at"), _MARKET_TTL):
            status, freshness = "degraded", "stale"
    elif _usable_entry(entry):
        status, freshness = "degraded", "stale"
    period_return = low = high = volume_ratio = None
    if len(bars) >= 2 and close is not None:
        first_close = _parse_float(bars[0].get("close"))
        if first_close:
            period_return = (close - first_close) / first_close * 100
        lows = [_parse_float(bar.get("low")) for bar in bars]
        highs = [_parse_float(bar.get("high")) for bar in bars]
        if all(value is not None for value in lows + highs):
            low = min(value for value in lows if value is not None)
            high = max(value for value in highs if value is not None)
        latest_volume = _parse_float(bars[-1].get("volume"))
        preceding = [_parse_float(bar.get("volume")) for bar in bars[:-1]]
        valid = [value for value in preceding if value is not None]
        if latest_volume is not None and valid and (average := sum(valid) / len(valid)) > 0:
            volume_ratio = latest_volume / average
    return {
        "symbol": symbol, "status": status, "freshness": freshness,
        "reason_code": "ok" if status == "healthy" else ("stale_cache" if status == "degraded" else "unavailable"),
        "observed_at": entry.get("market_fetched_at") if isinstance(entry.get("market_fetched_at"), str) else None,
        "close_date": bars[-1].get("date") if bars else None,
        "price": close, "change": change, "change_percent": change_percent, "history": bars,
        "period_return_percent": period_return, "period_low": low, "period_high": high, "volume_ratio": volume_ratio,
    }


def _build_snapshot(cache: dict[str, Any], symbols: list[str], *, fetched_live: set[str] | None = None, disabled: bool = False, reason_code: str = "ok") -> dict[str, Any]:
    fetched_live = fetched_live or set()
    entries = [_ticker_from_entry(symbol, cache["symbols"].get(symbol, {}), fetched_live=symbol in fetched_live) for symbol in symbols]
    if disabled:
        status, freshness, entries = "disabled", "none", []
    elif not symbols:
        status, freshness, reason_code = "unavailable", "none", "not_configured"
    else:
        usable = [entry for entry in entries if entry["status"] != "unavailable"]
        if len(usable) == len(entries) and all(entry["status"] == "healthy" for entry in entries):
            status = "healthy"
            freshness = "live" if entries and all(entry["freshness"] == "live" for entry in entries) else "fresh_cache"
        elif usable:
            status = "degraded"
            freshness = "stale" if any(entry["freshness"] == "stale" for entry in usable) else "live"
            reason_code = "partial_data"
        else:
            status, freshness = "unavailable", "none"
            reason_code = reason_code if reason_code != "ok" else "unavailable"
    return {"status": status, "freshness": freshness, "reason_code": reason_code, "observed_at": _iso_utc(), "collection_revision": cache["collection_revision"], "tickers": entries}


def _simulate_history(symbol: str, now: datetime) -> list[dict[str, Any]]:
    base = _DEMO_BASE_PRICES.get(symbol, 100.0)
    history: list[dict[str, Any]] = []
    for index in range(_DISPLAY_HISTORY_LENGTH):
        stamp = now - timedelta(days=_DISPLAY_HISTORY_LENGTH - index - 1)
        close = round(base * (1 + math.sin(stamp.timestamp() / 86_400 + index) * 0.015 + index * 0.001), 2)
        opening = round(close * 0.997, 2)
        history.append({"date": stamp.date().isoformat(), "open": opening, "high": round(close * 1.006, 2), "low": round(close * 0.994, 2), "close": close, "volume": round(base * 100_000 * (1 + index / 100), 2)})
    return history


def _demo_snapshot() -> dict[str, Any]:
    now = _now_utc()
    symbols = _configured_symbols() or list(_DEMO_SYMBOLS)
    cache = _empty_cache()
    cache["collection_revision"] = int(now.timestamp())
    for symbol in symbols:
        cache["symbols"][symbol] = {"history": _simulate_history(symbol, now), "market_fetched_at": _iso_utc(now)}
    return _build_snapshot(cache, symbols, fetched_live=set(symbols))


def refresh_market_data() -> dict[str, Any]:
    """Refresh provider-backed cache. Only telemetry collection may call this."""
    if DEMO_MODE:
        return _demo_snapshot()
    symbols = _configured_symbols()
    if not symbols or not _get_api_key():
        return _build_snapshot(_empty_cache(), symbols or [], reason_code="not_configured")
    api_key = _get_api_key()
    assert api_key is not None
    with _MARKET_LOCK:
        cache = _read_cache()
        entries: dict[str, Any] = cache["symbols"]
        fetched_live: set[str] = set()
        reason_code = "ok"
        global_cooldown = _cooldown_remaining(cache.get("cooldown_until")) > 0
        for symbol in symbols:
            entry = entries.get(symbol)
            if not isinstance(entry, dict):
                entry = {}
                entries[symbol] = entry
            if _is_fresh(entry.get("market_fetched_at"), _MARKET_TTL):
                continue
            if global_cooldown or _cooldown_remaining(entry.get("cooldown_until")) > 0:
                reason_code = "cooldown"
                continue
            payload, error = _alpha_vantage_get({"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": api_key})
            if error:
                reason_code = error
                cache["cooldown_until"] = _iso_utc(_now_utc() + _COOLDOWN_DURATION)
                global_cooldown = True
                continue
            history = _parse_daily_history(payload or {})
            if history is None:
                reason_code = "invalid_series"
                entry["cooldown_until"] = _iso_utc(_now_utc() + _SYMBOL_COOLDOWN_DURATION)
                continue
            now_iso = _iso_utc()
            last, prior = history[-1], history[-2]
            entry.update({"history": history, "price": last["close"], "change": last["close"] - prior["close"], "change_percent": ((last["close"] - prior["close"]) / prior["close"] * 100 if prior["close"] else None), "market_fetched_at": now_iso})
            fetched_live.add(symbol)
        cache["collection_revision"] += 1
        _write_cache(cache)
        return _build_snapshot(cache, symbols, fetched_live=fetched_live, reason_code=reason_code)


def read_market_data() -> dict[str, Any]:
    """Return display data without provider, cache, or cooldown mutation."""
    if DEMO_MODE:
        return _demo_snapshot()
    symbols = _configured_symbols() or []
    if not _market_enabled():
        return _build_snapshot(_read_cache(), symbols, disabled=True, reason_code="disabled")
    if not symbols or not _get_api_key():
        return _build_snapshot(_read_cache(), symbols, reason_code="not_configured")
    return _build_snapshot(_read_cache(), symbols)


def collect_market() -> ConnectorResult:
    """Translate market collection into the common telemetry connector contract."""
    payload = refresh_market_data()
    summaries = [{key: ticker[key] for key in ("symbol", "status", "freshness", "reason_code", "close_date", "price", "change_percent")} for ticker in payload["tickers"]]
    return ConnectorResult(name="market", status=payload["status"], freshness=payload["freshness"], reason_code=payload["reason_code"], observed_at=payload["observed_at"], display_text=f"{len(summaries)} market symbols", data={"collection_revision": payload["collection_revision"], "tickers": summaries})
