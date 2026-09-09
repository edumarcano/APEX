"""Alpha Vantage EOD market collection and cache-backed display data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
from copy import deepcopy
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
_CACHE_VERSION = 3
_ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_FAILURE_BACKOFF_DAYS = 8
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
    return {
        "version": _CACHE_VERSION,
        "provider_next_attempt_date": None,
        "collection_revision": 0,
        "symbols": {},
    }


def _parse_date(raw: object) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _utc_today() -> date:
    return _now_utc().date()


def _date_from_timestamp(raw: object) -> str | None:
    parsed = _parse_iso(raw)
    return parsed.date().isoformat() if parsed is not None else None


def _normalize_cache_entry(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    entry = dict(raw)
    successful_date = _parse_date(entry.get("last_successful_fetch_date"))
    if successful_date is None:
        derived = _date_from_timestamp(entry.get("market_fetched_at"))
        if derived is not None:
            entry["last_successful_fetch_date"] = derived
    attempt_date = _parse_date(entry.get("last_attempt_date"))
    if attempt_date is None and _parse_date(entry.get("last_successful_fetch_date")) is not None:
        entry["last_attempt_date"] = entry["last_successful_fetch_date"]
    failures = entry.get("consecutive_failures")
    entry["consecutive_failures"] = failures if isinstance(failures, int) and failures >= 0 else 0
    if _parse_date(entry.get("next_attempt_date")) is None:
        entry.pop("next_attempt_date", None)
    if not isinstance(entry.get("last_error_code"), str):
        entry.pop("last_error_code", None)
    entry.pop("cooldown_until", None)
    return entry


def _read_cache() -> dict[str, Any]:
    try:
        with _cache_path().open(encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(raw, dict):
        return _empty_cache()
    raw_symbols = raw.get("symbols") if isinstance(raw.get("symbols"), dict) else {}
    symbols = {symbol: _normalize_cache_entry(entry) for symbol, entry in raw_symbols.items() if isinstance(symbol, str)}
    revision = raw.get("collection_revision")
    return {
        "version": _CACHE_VERSION,
        "provider_next_attempt_date": (
            raw.get("provider_next_attempt_date")
            if _parse_date(raw.get("provider_next_attempt_date")) is not None
            else None
        ),
        "collection_revision": revision if isinstance(revision, int) and revision >= 0 else 0,
        "symbols": symbols,
    }


def _write_cache(cache: dict[str, Any]) -> bool:
    path = _cache_path()
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(cache, handle, separators=(",", ":"))
        temporary.replace(path)
        return True
    except (OSError, TypeError) as exc:
        sys.stderr.write(f"[MARKET][CACHE] {exc}\n")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _configured_symbols() -> list[str] | None:
    symbols = list(get_settings_store().get_snapshot().market.symbols)
    return symbols or None


def _market_enabled() -> bool:
    return bool(get_settings_store().get_snapshot().features.market)


def _get_api_key() -> str | None:
    raw = os.getenv("ALPHA_VANTAGE_API_KEY")
    return raw.strip() if raw and raw.strip() else None


def _successful_today(entry: dict[str, Any], today: date | None = None) -> bool:
    return _parse_date(entry.get("last_successful_fetch_date")) == (today or _utc_today())


def _attempted_today(entry: dict[str, Any], today: date | None = None) -> bool:
    return _parse_date(entry.get("last_attempt_date")) == (today or _utc_today())


def _backoff_active(entry: dict[str, Any], today: date | None = None) -> bool:
    next_attempt = _parse_date(entry.get("next_attempt_date"))
    return next_attempt is not None and (today or _utc_today()) < next_attempt


def _provider_backoff_active(cache: dict[str, Any], today: date | None = None) -> bool:
    next_attempt = _parse_date(cache.get("provider_next_attempt_date"))
    return next_attempt is not None and (today or _utc_today()) < next_attempt


def _record_failure(entry: dict[str, Any], reason_code: str, today: date) -> None:
    previous = entry.get("consecutive_failures")
    failures = (previous if isinstance(previous, int) and previous >= 0 else 0) + 1
    delay_days = min(2 ** (failures - 1), _MAX_FAILURE_BACKOFF_DAYS)
    entry.update(
        {
            "last_attempt_date": today.isoformat(),
            "consecutive_failures": failures,
            "next_attempt_date": (today + timedelta(days=delay_days)).isoformat(),
            "last_error_code": reason_code,
        }
    )


def _record_success(entry: dict[str, Any], history: list[dict[str, Any]], today: date) -> None:
    now_iso = _iso_utc()
    last, prior = history[-1], history[-2]
    entry.update(
        {
            "history": history,
            "price": last["close"],
            "change": last["close"] - prior["close"],
            "change_percent": (
                (last["close"] - prior["close"]) / prior["close"] * 100
                if prior["close"]
                else None
            ),
            "market_fetched_at": now_iso,
            "last_successful_fetch_date": today.isoformat(),
            "last_attempt_date": today.isoformat(),
            "consecutive_failures": 0,
            "next_attempt_date": None,
            "last_error_code": None,
        }
    )


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
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in {401, 403}:
            return None, "invalid_credentials"
        if status_code == 429:
            return None, "rate_limited"
        return None, "provider_error" if status_code is not None and status_code >= 500 else "http_error"
    except requests.ConnectionError:
        return None, "connection_error"
    except requests.RequestException:
        return None, "http_error"
    except ValueError:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_payload"
    note = payload.get("Note")
    information = payload.get("Information")
    provider_message = note if isinstance(note, str) else information if isinstance(information, str) else ""
    normalized_message = provider_message.casefold()
    if provider_message:
        if "25 requests per day" in normalized_message or "daily" in normalized_message and "limit" in normalized_message:
            return None, "daily_rate_limit"
        if any(fragment in normalized_message for fragment in ("rate limit", "call frequency", "api call volume")):
            return None, "rate_limited"
        if "api key" in normalized_message and any(fragment in normalized_message for fragment in ("invalid", "missing", "please claim")):
            return None, "invalid_credentials"
        return None, "provider_error"
    if payload.get("Error Message"):
        return None, "invalid_symbol"
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
    stored_bars = [bar for bar in history if isinstance(bar, dict)]
    bars = stored_bars[-_DISPLAY_HISTORY_LENGTH:]
    close = _parse_float(bars[-1].get("close")) if bars else _parse_float(entry.get("price"))
    previous = _parse_float(bars[-2].get("close")) if len(bars) >= 2 else None
    change = close - previous if close is not None and previous is not None else _parse_float(entry.get("change"))
    change_percent = change / previous * 100 if change is not None and previous else _parse_float(entry.get("change_percent"))
    status, freshness = "unavailable", "none"
    if len(bars) >= 2:
        status, freshness = "healthy", ("live" if fetched_live else "fresh_cache")
        if not fetched_live and not _successful_today(entry):
            status, freshness = "degraded", "stale"
    elif _usable_entry(entry):
        status, freshness = "degraded", "stale"
    last_error = entry.get("last_error_code") if isinstance(entry.get("last_error_code"), str) else None
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
        if len(stored_bars) >= _DISPLAY_HISTORY_LENGTH + 1:
            volume_window = stored_bars[-(_DISPLAY_HISTORY_LENGTH + 1):]
            latest_volume = _parse_float(volume_window[-1].get("volume"))
            preceding = [_parse_float(bar.get("volume")) for bar in volume_window[:-1]]
            if latest_volume is not None and all(value is not None for value in preceding):
                average = sum(value for value in preceding if value is not None) / _DISPLAY_HISTORY_LENGTH
                if average > 0:
                    volume_ratio = latest_volume / average
    return {
        "symbol": symbol, "status": status, "freshness": freshness,
        "reason_code": "ok" if status == "healthy" else (last_error or ("stale_cache" if status == "degraded" else "unavailable")),
        "observed_at": entry.get("market_fetched_at") if isinstance(entry.get("market_fetched_at"), str) else None,
        "close_date": bars[-1].get("date") if bars else None,
        "last_successful_fetch_date": entry.get("last_successful_fetch_date") if _parse_date(entry.get("last_successful_fetch_date")) is not None else None,
        "last_attempt_date": entry.get("last_attempt_date") if _parse_date(entry.get("last_attempt_date")) is not None else None,
        "next_attempt_date": entry.get("next_attempt_date") if _parse_date(entry.get("next_attempt_date")) is not None else None,
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
            if any(entry["freshness"] == "stale" for entry in usable):
                freshness = "stale"
            elif any(entry["freshness"] == "live" for entry in usable):
                freshness = "live"
            else:
                freshness = "fresh_cache"
            specific_reason = next(
                (
                    entry["reason_code"]
                    for entry in entries
                    if entry["reason_code"] not in {"ok", "unavailable", "stale_cache"}
                ),
                None,
            )
            reason_code = specific_reason or (reason_code if reason_code != "ok" else "partial_data")
        else:
            status, freshness = "unavailable", "none"
            specific_reason = next(
                (entry["reason_code"] for entry in entries if entry["reason_code"] != "unavailable"),
                None,
            )
            reason_code = specific_reason or (reason_code if reason_code != "ok" else "unavailable")
    return {"status": status, "freshness": freshness, "reason_code": reason_code, "observed_at": _iso_utc(), "collection_revision": cache["collection_revision"], "tickers": entries}


def _simulate_history(symbol: str, now: datetime) -> list[dict[str, Any]]:
    base = _DEMO_BASE_PRICES.get(symbol, 100.0)
    history: list[dict[str, Any]] = []
    session_date = now.date()
    while session_date.weekday() >= 5:
        session_date -= timedelta(days=1)
    session_dates: list[date] = []
    while len(session_dates) < _DISPLAY_HISTORY_LENGTH + 1:
        if session_date.weekday() < 5:
            session_dates.append(session_date)
        session_date -= timedelta(days=1)
    session_dates.reverse()
    for index, trading_date in enumerate(session_dates):
        close = round(base * (1 + math.sin(trading_date.toordinal() + index) * 0.015 + index * 0.001), 2)
        opening = round(close * 0.997, 2)
        history.append({"date": trading_date.isoformat(), "open": opening, "high": round(close * 1.006, 2), "low": round(close * 0.994, 2), "close": close, "volume": round(base * 100_000 * (1 + index / 100), 2)})
    return history


def _demo_collection_revision(session_date: date, symbols: list[str]) -> int:
    """Return a stable, runtime-independent revision for one demo data shape."""
    material = json.dumps(
        [session_date.isoformat(), *symbols],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:6], "big")


def _demo_snapshot() -> dict[str, Any]:
    now = _now_utc()
    symbols = _configured_symbols() or list(_DEMO_SYMBOLS)
    cache = _empty_cache()
    session_date = now.date()
    while session_date.weekday() >= 5:
        session_date -= timedelta(days=1)
    cache["collection_revision"] = _demo_collection_revision(session_date, symbols)
    for symbol in symbols:
        cache["symbols"][symbol] = {"history": _simulate_history(symbol, now), "market_fetched_at": _iso_utc(now)}
    return _build_snapshot(cache, symbols, fetched_live=set(symbols))


def _as_connector_result(payload: dict[str, Any]) -> ConnectorResult:
    summaries = [
        {
            key: ticker[key]
            for key in ("symbol", "status", "freshness", "reason_code", "close_date", "price", "change_percent")
        }
        for ticker in payload["tickers"]
    ]
    return ConnectorResult(
        name="market",
        status=payload["status"],
        freshness=payload["freshness"],
        reason_code=payload["reason_code"],
        observed_at=payload["observed_at"],
        display_text=f"{len(summaries)} market symbols",
        data={"collection_revision": payload["collection_revision"], "tickers": summaries},
    )


def collect_demo_market() -> ConnectorResult:
    """Build the configured synthetic market result used by DEMO_MODE telemetry."""
    if not _market_enabled():
        return _as_connector_result(
            _build_snapshot(_empty_cache(), [], disabled=True, reason_code="disabled")
        )
    return _as_connector_result(_demo_snapshot())


def refresh_market_data() -> dict[str, Any]:
    """Refresh provider-backed cache. Only telemetry collection may call this."""
    if DEMO_MODE:
        if not _market_enabled():
            return _build_snapshot(_empty_cache(), [], disabled=True, reason_code="disabled")
        return _demo_snapshot()
    symbols = _configured_symbols()
    if not symbols or not _get_api_key():
        return _build_snapshot(_empty_cache(), symbols or [], reason_code="not_configured")
    api_key = _get_api_key()
    assert api_key is not None
    with _MARKET_LOCK:
        cache = _read_cache()
        persisted_cache = deepcopy(cache)
        entries: dict[str, Any] = cache["symbols"]
        fetched_live: set[str] = set()
        reason_code = "ok"
        today = _utc_today()
        provider_backoff = _provider_backoff_active(cache, today)
        for symbol in symbols:
            entry = entries.get(symbol)
            if not isinstance(entry, dict):
                entry = {}
                entries[symbol] = entry
            if _successful_today(entry, today) or _attempted_today(entry, today) or _backoff_active(entry, today):
                continue
            if provider_backoff:
                reason_code = "provider_backoff"
                continue
            previous_attempt_date = entry.get("last_attempt_date")
            entry["last_attempt_date"] = today.isoformat()
            if not _write_cache(cache):
                if previous_attempt_date is None:
                    entry.pop("last_attempt_date", None)
                else:
                    entry["last_attempt_date"] = previous_attempt_date
                reason_code = "cache_write_error"
                continue
            persisted_cache = deepcopy(cache)
            payload, error = _alpha_vantage_get({"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": api_key})
            if error:
                reason_code = error
                _record_failure(entry, error, today)
                if error in {
                    "connection_error",
                    "daily_rate_limit",
                    "http_error",
                    "invalid_credentials",
                    "invalid_json",
                    "invalid_payload",
                    "provider_error",
                    "rate_limited",
                    "timeout",
                }:
                    cache["provider_next_attempt_date"] = (today + timedelta(days=1)).isoformat()
                    provider_backoff = True
                continue
            history = _parse_daily_history(payload or {})
            if history is None:
                reason_code = "invalid_series"
                _record_failure(entry, reason_code, today)
                continue
            _record_success(entry, history, today)
            fetched_live.add(symbol)
        if not provider_backoff:
            cache["provider_next_attempt_date"] = None
        cache["collection_revision"] += 1
        if not _write_cache(cache):
            snapshot = _build_snapshot(persisted_cache, symbols, reason_code="cache_write_error")
            if snapshot["status"] == "healthy":
                snapshot["status"] = "degraded"
                snapshot["freshness"] = "fresh_cache"
            return snapshot
        return _build_snapshot(cache, symbols, fetched_live=fetched_live, reason_code=reason_code)


def read_market_data() -> dict[str, Any]:
    """Return display data without provider, cache, or cooldown mutation."""
    if DEMO_MODE:
        if not _market_enabled():
            return _build_snapshot(_empty_cache(), [], disabled=True, reason_code="disabled")
        return _demo_snapshot()
    symbols = _configured_symbols() or []
    if not _market_enabled():
        return _build_snapshot(_read_cache(), symbols, disabled=True, reason_code="disabled")
    if not symbols or not _get_api_key():
        return _build_snapshot(_empty_cache(), symbols, reason_code="not_configured")
    return _build_snapshot(_read_cache(), symbols)


def collect_market() -> ConnectorResult:
    """Translate market collection into the common telemetry connector contract."""
    payload = refresh_market_data()
    return _as_connector_result(payload)
