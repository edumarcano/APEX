"""Sports connectors with typed F1 and football briefing results."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from clients.http_sessions import get_connector_http_session
from core.connectors.models import ConnectorResult, utc_now_iso
from core.settings import get_settings_store

load_dotenv()


F1_CACHE_FILENAME = ".f1_cache.json"
F1_CACHE_TTL = timedelta(hours=24)
FOOTBALL_CACHE_FILENAME = ".football_cache.json"
FOOTBALL_CACHE_TTL = timedelta(hours=6)
try:
    EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    EASTERN_TZ = timezone.utc


def _get_f1_cache_path() -> str:
    return os.path.join(os.path.dirname(__file__), F1_CACHE_FILENAME)


def _read_f1_cache() -> Optional[Dict[str, Any]]:
    cache_path = _get_f1_cache_path()
    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except Exception:
        return None


def _write_f1_cache(f1_map: Dict[str, Any]) -> None:
    try:
        cache_payload = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "f1_map": f1_map,
        }
        cache_path = _get_f1_cache_path()
        with open(cache_path, "w", encoding="utf-8") as cache_file:
            json.dump(cache_payload, cache_file, separators=(",", ":"))
    except (OSError, TypeError):
        sys.stderr.write("[SPORTS][F1][CACHE] write_failed\n")


def _is_f1_cache_fresh(cache_payload: Dict[str, Any]) -> bool:
    cached_at_raw = cache_payload.get("cached_at")
    if not isinstance(cached_at_raw, str):
        return False

    try:
        cached_at = datetime.fromisoformat(cached_at_raw)
    except ValueError:
        return False

    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)

    now_utc = datetime.now(timezone.utc)
    return now_utc - cached_at <= F1_CACHE_TTL


def _safe_parse_utc_datetime(date_value: str, time_value: str) -> Optional[datetime]:
    if not date_value:
        return None

    clean_time = (time_value or "00:00:00").replace("Z", "")
    iso_value = f"{date_value}T{clean_time}+00:00"
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        return None


def _format_est_edt(dt_utc: Optional[datetime]) -> str:
    if dt_utc is None:
        return "Unscheduled"

    dt_est = dt_utc.astimezone(EASTERN_TZ)
    return dt_est.strftime("%A, %B %d at %I:%M %p %Z")


def _relative_week_label(dt_utc: Optional[datetime]) -> str:
    if dt_utc is None:
        return "Unscheduled"

    now_local = datetime.now(EASTERN_TZ)
    race_local = dt_utc.astimezone(EASTERN_TZ)
    current_week_start = now_local.date() - timedelta(days=now_local.weekday())
    race_week_start = race_local.date() - timedelta(days=race_local.weekday())
    week_offset = max(0, (race_week_start - current_week_start).days // 7)

    if week_offset == 0:
        return "This week"
    if week_offset == 1:
        return "Next week"
    return f"In {week_offset} weeks"


def _build_f1_map_from_race(race: Dict[str, Any]) -> Dict[str, Any]:
    race_dt_utc = _safe_parse_utc_datetime(race.get("date", ""), race.get("time", ""))
    sprint = race.get("Sprint")
    sprint_available = isinstance(sprint, dict)
    sprint_dt_utc = None
    if sprint_available:
        sprint_dt_utc = _safe_parse_utc_datetime(
            sprint.get("date", ""),
            sprint.get("time", ""),
        )
        sprint_available = sprint_dt_utc is not None

    return {
        "raceName": race.get("raceName", "Unknown"),
        "round": race.get("round", "Unknown"),
        "country": (
            race.get("Circuit", {})
            .get("Location", {})
            .get("country", "Unknown")
        ),
        "raceDateTimeEST": _format_est_edt(race_dt_utc),
        "relativeWeek": _relative_week_label(race_dt_utc),
        "sprintScheduled": sprint_available,
        "sprintDateTimeEST": _format_est_edt(sprint_dt_utc) if sprint_available else "Unscheduled",
    }


def _is_valid_f1_map(f1_map: object) -> bool:
    """Return whether cached F1 telemetry has the facts required downstream."""
    if not isinstance(f1_map, dict):
        return False
    required_text = ("raceName", "raceDateTimeEST", "relativeWeek")
    if not all(
        isinstance(f1_map.get(key), str) and bool(f1_map[key].strip())
        for key in required_text
    ):
        return False
    return isinstance(f1_map.get("sprintScheduled"), bool)


def collect_f1() -> ConnectorResult:
    """Collect Formula 1 next-race telemetry as a typed connector result."""
    observed_at = utc_now_iso()
    cache_payload = _read_f1_cache()
    cached_map = None
    if cache_payload and _is_valid_f1_map(cache_payload.get("f1_map")):
        cached_map = cache_payload["f1_map"]

    try:
        f1_url = "https://api.jolpi.ca/ergast/f1/current/next.json"
        if cache_payload and cached_map and _is_f1_cache_fresh(cache_payload):
            f1_map = cached_map
            freshness = "fresh_cache"
        else:
            session = get_connector_http_session("sports")
            response = (
                session.get(f1_url, timeout=10)
                if session is not None
                else requests.get(f1_url, timeout=10)
            )
            response.raise_for_status()
            f1_data = response.json()
            races = f1_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
            if not isinstance(races, list) or not races or not isinstance(races[0], dict):
                raise ValueError("No F1 races in payload.")
            f1_map = _build_f1_map_from_race(races[0])
            if not _is_valid_f1_map(f1_map):
                raise ValueError("Invalid F1 race payload.")
            _write_f1_cache(f1_map)
            freshness = "live"
        return ConnectorResult(
            name="f1",
            status="healthy",
            freshness=freshness,  # type: ignore[arg-type]
            reason_code="ok",
            observed_at=observed_at,
            display_text=f"F1_DATA:{json.dumps(f1_map, separators=(',', ':'))}",
            data={"f1_map": f1_map, "cache_refreshed": True},
        )
    except Exception:
        sys.stderr.write("[SPORTS][F1] fetch_failed\n")
        if cached_map:
            return ConnectorResult(
                name="f1",
                status="degraded",
                freshness="stale",
                reason_code="stale_cache",
                observed_at=observed_at,
                display_text=f"F1_DATA:{json.dumps(cached_map, separators=(',', ':'))}",
                data={"f1_map": cached_map, "cache_refreshed": False},
            )
        return ConnectorResult(
            name="f1",
            status="unavailable",
            freshness="none",
            reason_code="provider_error",
            observed_at=observed_at,
            display_text="F1 race telemetry unavailable.",
            data={"f1_map": None, "cache_refreshed": False},
        )


def _get_football_cache_path() -> str:
    return os.path.join(os.path.dirname(__file__), FOOTBALL_CACHE_FILENAME)


def _parse_utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _is_valid_football_fixture(value: object, *, now: datetime) -> bool:
    if not isinstance(value, dict):
        return False
    required_text = ("fixture_id", "team", "opponent", "home_or_away", "competition", "kickoff_at")
    if not all(isinstance(value.get(key), str) and value[key].strip() for key in required_text):
        return False
    if value.get("home_or_away") not in {"home", "away"}:
        return False
    if isinstance(value.get("team_id"), bool) or not isinstance(value.get("team_id"), int):
        return False
    if isinstance(value.get("competition_id"), bool) or not isinstance(value.get("competition_id"), int):
        return False
    kickoff = _parse_utc_datetime(value.get("kickoff_at"))
    return kickoff is not None and kickoff > now


def _read_football_cache(*, now: datetime) -> dict[int, tuple[datetime, dict[str, Any]]]:
    try:
        with open(_get_football_cache_path(), "r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, ValueError, TypeError):
        return {}
    entries = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}
    valid: dict[int, tuple[datetime, dict[str, Any]]] = {}
    for raw_id, entry in entries.items():
        try:
            team_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        cached_at = _parse_utc_datetime(entry.get("cached_at"))
        fixture = entry.get("fixture")
        if cached_at is not None and _is_valid_football_fixture(fixture, now=now):
            valid[team_id] = (cached_at, fixture)
    return valid


def _write_football_cache(entries: dict[int, dict[str, Any]]) -> None:
    try:
        payload = {
            "teams": {
                str(team_id): {"cached_at": utc_now_iso(), "fixture": fixture}
                for team_id, fixture in entries.items()
            }
        }
        with open(_get_football_cache_path(), "w", encoding="utf-8") as cache_file:
            json.dump(payload, cache_file, separators=(",", ":"))
    except (OSError, TypeError):
        sys.stderr.write("[SPORTS][FOOTBALL][CACHE] write_failed\n")


def _normalize_football_match(match: object, *, team_id: int, team_name: str, now: datetime) -> dict[str, Any] | None:
    if not isinstance(match, dict):
        return None
    home = match.get("homeTeam")
    away = match.get("awayTeam")
    competition = match.get("competition")
    kickoff = _parse_utc_datetime(match.get("utcDate"))
    if not isinstance(home, dict) or not isinstance(away, dict) or not isinstance(competition, dict) or kickoff is None or kickoff <= now:
        return None
    home_id, away_id = home.get("id"), away.get("id")
    if home_id == team_id:
        opponent, home_or_away = away.get("name"), "home"
    elif away_id == team_id:
        opponent, home_or_away = home.get("name"), "away"
    else:
        return None
    fixture_id = match.get("id")
    competition_id = competition.get("id")
    competition_name = competition.get("name")
    if isinstance(fixture_id, bool) or not isinstance(fixture_id, int) or isinstance(competition_id, bool) or not isinstance(competition_id, int):
        return None
    if not all(isinstance(value, str) and value.strip() for value in (opponent, competition_name)):
        return None
    fixture = {
        "fixture_id": str(fixture_id),
        "team_id": team_id,
        "team": team_name,
        "opponent": opponent.strip(),
        "home_or_away": home_or_away,
        "competition_id": competition_id,
        "competition": competition_name.strip(),
        "kickoff_at": kickoff.isoformat(),
    }
    return fixture if _is_valid_football_fixture(fixture, now=now) else None


def _football_display_text(fixtures: list[dict[str, Any]]) -> str:
    if not fixtures:
        return "No upcoming football fixtures."
    return " ".join(
        f"{fixture['team']}: {'Home' if fixture['home_or_away'] == 'home' else 'Away'} vs {fixture['opponent']} ({fixture['competition']})."
        for fixture in fixtures
    )


def collect_football(*, force: bool = False) -> ConnectorResult:
    """Collect the next scheduled fixture for each configured followed team."""
    observed_at = utc_now_iso()
    now = datetime.now(timezone.utc)
    teams = get_settings_store().get_snapshot().football.teams
    if not teams:
        return ConnectorResult(name="football", status="unavailable", freshness="none", reason_code="configuration_failure", observed_at=observed_at, display_text="Football fixture configuration is unavailable.", data={"fixtures": [], "configured_team_count": 0})
    football_api_key = os.getenv("FOOTBALL_API_KEY")
    if not football_api_key:
        return ConnectorResult(name="football", status="unavailable", freshness="none", reason_code="missing_credentials", observed_at=observed_at, display_text="Football fixture telemetry unavailable.", data={"fixtures": [], "configured_team_count": len(teams)})

    cache = _read_football_cache(now=now)
    fixtures: list[dict[str, Any]] = []
    failures: list[str] = []
    live_entries: dict[int, dict[str, Any]] = {}
    fresh_cache_used = False
    headers = {"X-Auth-Token": football_api_key}
    for team in teams:
        cached = cache.get(team.id)
        cache_is_fresh = cached is not None and now - cached[0] <= FOOTBALL_CACHE_TTL
        if cached is not None and cache_is_fresh and not force:
            fixtures.append(cached[1])
            fresh_cache_used = True
            continue
        try:
            url = (
                "https://api.football-data.org/v4/teams/"
                f"{team.id}/matches?status=SCHEDULED&limit=1"
            )
            session = get_connector_http_session("sports")
            response = (
                session.get(url, headers=headers, timeout=10)
                if session is not None
                else requests.get(url, headers=headers, timeout=10)
            )
            if response.status_code == 429:
                raise RuntimeError("throttled")
            if response.status_code != 200:
                raise RuntimeError("provider_error")
            payload = response.json()
            matches = payload.get("matches") if isinstance(payload, dict) else None
            if not isinstance(matches, list):
                raise RuntimeError("malformed_payload")
            if matches:
                fixture = _normalize_football_match(matches[0], team_id=team.id, team_name=team.name, now=now)
                if fixture is None:
                    raise RuntimeError("malformed_payload")
                fixtures.append(fixture)
                live_entries[team.id] = fixture
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            reason = str(exc) if str(exc) in {"throttled", "provider_error", "malformed_payload"} else "network_error"
            failures.append(reason)
            if cached is not None:
                fixtures.append(cached[1])

    if live_entries:
        _write_football_cache({**{team_id: fixture for team_id, (_, fixture) in cache.items()}, **live_entries})
    fixtures.sort(key=lambda fixture: fixture["kickoff_at"])
    data = {"fixtures": fixtures, "configured_team_count": len(teams)}
    if failures:
        if fixtures:
            return ConnectorResult(name="football", status="degraded", freshness="stale", reason_code=failures[0], observed_at=observed_at, display_text=_football_display_text(fixtures), data=data)
        return ConnectorResult(name="football", status="unavailable", freshness="none", reason_code=failures[0], observed_at=observed_at, display_text="Football fixture telemetry unavailable.", data=data)
    return ConnectorResult(name="football", status="healthy", freshness="fresh_cache" if fresh_cache_used and not live_entries else "live", reason_code="ok", observed_at=observed_at, display_text=_football_display_text(fixtures), data=data)


def fetch_sports_snapshot(
    *,
    f1: bool,
    football: bool,
) -> tuple[str, bool, Dict[str, Any] | None]:
    """Compatibility snapshot returning combined text plus F1 freshness/map."""
    segments: list[str] = []
    f1_cache_refreshed = True
    resolved_f1_map: Dict[str, Any] | None = None

    if f1:
        f1_result = collect_f1()
        segments.append(f1_result.display_text)
        f1_cache_refreshed = bool(f1_result.data.get("cache_refreshed", False))
        f1_map = f1_result.data.get("f1_map")
        resolved_f1_map = f1_map if isinstance(f1_map, dict) else None

    if football:
        segments.append(collect_football().display_text)

    return " ".join(segments), f1_cache_refreshed, resolved_f1_map


def fetch_sports_data() -> tuple[str, bool]:
    """Compatibility façade returning the legacy report/freshness pair."""
    modules = get_settings_store().get_snapshot().modules
    report, refreshed, _f1_map = fetch_sports_snapshot(
        f1=modules.f1,
        football=modules.football,
    )
    return report, refreshed


def fetch_f1_driver_standings() -> Dict[str, Any]:
    """Fetch current Formula 1 driver championship standings from Ergast."""
    url = "https://api.jolpi.ca/ergast/f1/current/driverStandings.json"

    try:
        session = get_connector_http_session("sports")
        response = (
            session.get(url, timeout=10)
            if session is not None
            else requests.get(url, timeout=10)
        )
        response.raise_for_status()
        data = response.json()

        mr_data = data.get("MRData", {})
        standings_table = mr_data.get("StandingsTable", {})
        season = str(standings_table.get("season", ""))
        standings_lists = standings_table.get("StandingsLists", [])

        if not standings_lists:
            return {"season": season, "round": "", "standings": []}

        standings_list = standings_lists[0]
        round_value = str(standings_list.get("round", ""))
        driver_standings = standings_list.get("DriverStandings", [])

        standings: list[Dict[str, Any]] = []
        for entry in driver_standings:
            driver = entry.get("Driver", {})
            constructors = entry.get("Constructors", [])
            team = constructors[0].get("name", "") if constructors else ""
            given_name = driver.get("givenName", "")
            family_name = driver.get("familyName", "")
            driver_name = f"{given_name} {family_name}".strip()
            driver_code = driver.get("code") or driver.get("driverId", "")

            standings.append(
                {
                    "position": int(entry.get("position", 0)),
                    "points": float(entry.get("points", 0)),
                    "wins": int(entry.get("wins", 0)),
                    "driver_name": driver_name,
                    "driver_code": str(driver_code),
                    "team": team,
                }
            )

        return {"season": season, "round": round_value, "standings": standings}

    except Exception as exc:
        return {"error": str(exc)}


def fetch_f1_season_calendar() -> Dict[str, Any]:
    """Fetch the full Formula 1 race calendar for the current season from Ergast."""
    url = "https://api.jolpi.ca/ergast/f1/current.json"

    try:
        session = get_connector_http_session("sports")
        response = (
            session.get(url, timeout=10)
            if session is not None
            else requests.get(url, timeout=10)
        )
        response.raise_for_status()
        data = response.json()

        mr_data = data.get("MRData", {})
        race_table = mr_data.get("RaceTable", {})
        season = str(race_table.get("season", ""))
        races = race_table.get("Races", [])

        calendar: list[Dict[str, Any]] = []
        for race in races:
            circuit = race.get("Circuit", {})
            location = circuit.get("Location", {})
            calendar.append(
                {
                    "round": int(race.get("round", 0)),
                    "raceName": race.get("raceName", ""),
                    "circuitName": circuit.get("circuitName", ""),
                    "country": location.get("country", ""),
                    "date": race.get("date", ""),
                    "time": race.get("time", "") or "",
                }
            )

        return {"season": season, "calendar": calendar}

    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    report, _ = fetch_sports_data()
    print(f"[SPORTS]: {report}")
