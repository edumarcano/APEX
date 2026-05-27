import json
import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from core.config import MODULE_FOOTBALL, MODULE_F1

load_dotenv()


F1_CACHE_FILENAME = ".f1_cache.json"
F1_CACHE_TTL = timedelta(hours=24)
try:
    EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    EASTERN_TZ = timezone.utc


def _get_f1_cache_path() -> str:
    """Build the absolute filesystem path for the F1 cache file.

    Args:
        None

    Returns:
        str: Absolute path to `.f1_cache.json` in the `clients` directory.

    Raises:
        None.
    """
    return os.path.join(os.path.dirname(__file__), F1_CACHE_FILENAME)


def _read_f1_cache() -> Optional[Dict[str, Any]]:
    """Read and deserialize cached F1 telemetry data from disk.

    Args:
        None

    Returns:
        Optional[Dict[str, Any]]: Parsed cache payload if available and valid;
            otherwise `None`.

    Raises:
        None: All file and JSON parsing errors are handled internally.
    """
    cache_path = _get_f1_cache_path()
    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except Exception:
        return None


def _write_f1_cache(f1_map: Dict[str, Any]) -> None:
    """Persist the F1 telemetry map to the local cache file.

    Args:
        f1_map (Dict[str, Any]): Telemetry map to serialize into the cache.

    Returns:
        None: This function writes data as a side effect.

    Raises:
        OSError: If the cache file cannot be written.
        TypeError: If `f1_map` contains non-serializable values.
    """
    cache_payload = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "f1_map": f1_map,
    }
    cache_path = _get_f1_cache_path()
    with open(cache_path, "w", encoding="utf-8") as cache_file:
        json.dump(cache_payload, cache_file, separators=(",", ":"))


def _is_f1_cache_fresh(cache_payload: Dict[str, Any]) -> bool:
    """Determine whether the cache payload is still within the TTL window.

    Args:
        cache_payload (Dict[str, Any]): Cached payload containing `cached_at`
            metadata and telemetry fields.

    Returns:
        bool: `True` when the payload timestamp is within 24 hours; otherwise
            `False`.

    Raises:
        None: Invalid timestamp formats are handled and evaluated as stale.
    """
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
    """Safely parse UTC date and time strings into a timezone-aware datetime.

    Args:
        date_value (str): ISO-like race date string (e.g., `YYYY-MM-DD`).
        time_value (str): ISO-like UTC time string (e.g., `HH:MM:SSZ`).

    Returns:
        Optional[datetime]: Parsed UTC datetime when inputs are valid;
            otherwise `None`.

    Raises:
        None: Parsing errors are handled and return `None`.
    """
    if not date_value:
        return None

    clean_time = (time_value or "00:00:00").replace("Z", "")
    iso_value = f"{date_value}T{clean_time}+00:00"
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        return None


def _format_est_edt(dt_utc: Optional[datetime]) -> str:
    """Format a UTC datetime into an Eastern time display string.

    Args:
        dt_utc (Optional[datetime]): UTC datetime to convert and format.

    Returns:
        str: Human-readable Eastern date-time string, or `Unscheduled` when
            input is `None`.

    Raises:
        None.
    """
    if dt_utc is None:
        return "Unscheduled"

    dt_est = dt_utc.astimezone(EASTERN_TZ)
    return dt_est.strftime("%A, %B %d at %I:%M %p %Z")


def _relative_week_label(dt_utc: Optional[datetime]) -> str:
    """Generate a relative week label for the given race datetime.

    Args:
        dt_utc (Optional[datetime]): UTC race datetime used to compute week
            offset from current local Eastern time.

    Returns:
        str: One of `This week`, `Next week`, `In X weeks`, or `Unscheduled`.

    Raises:
        None.
    """
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
    """Build the normalized telemetry map for the next F1 race payload.

    Args:
        race (Dict[str, Any]): Race dictionary from the Jolpica/Ergast response.

    Returns:
        Dict[str, Any]: Normalized F1 telemetry map including race details,
            Eastern-formatted schedule values, relative week string, and sprint
            scheduling fields.

    Raises:
        None: Missing or malformed fields are handled with safe defaults.
    """
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


def fetch_sports_data() -> str:
    """
    Connect to sports APIs and retrieve current sports telemetry.

    Returns:
        str: A formatted string containing sports updates, or error
        messages if connections fail.
    """
    intel = []

    if MODULE_F1:
        cache_payload = _read_f1_cache()
        cached_map = None
        if cache_payload and isinstance(cache_payload.get("f1_map"), dict):
            cached_map = cache_payload["f1_map"]

        try:
            f1_url = "https://api.jolpi.ca/ergast/f1/current/next.json"
            if cache_payload and cached_map and _is_f1_cache_fresh(cache_payload):
                f1_map = cached_map
            else:
                response = requests.get(f1_url, timeout=10)
                response.raise_for_status()
                f1_data = response.json()
                races = f1_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
                if not races:
                    raise ValueError("No F1 races in payload.")
                race = races[0]
                f1_map = _build_f1_map_from_race(race)
                _write_f1_cache(f1_map)
            intel.append(f"F1_DATA:{json.dumps(f1_map, separators=(',', ':'))}")
        except Exception:
            if cached_map:
                intel.append(f"F1_DATA:{json.dumps(cached_map, separators=(',', ':'))}")
            else:
                intel.append("F1 race telemetry unavailable.")

    if MODULE_FOOTBALL:
        try:
            football_api_key = os.getenv("FOOTBALL_API_KEY")
            if not football_api_key:
                intel.append("Barcelona fixture telemetry unavailable.")
            else:
                barcelona_url = (
                    "https://api.football-data.org/v4/teams/81/matches"
                    "?status=SCHEDULED&limit=1"
                )
                headers = {"X-Auth-Token": football_api_key}
                response = requests.get(barcelona_url, headers=headers, timeout=10)

                if response.status_code == 429:
                    intel.append("Barcelona fixture telemetry throttled")
                elif response.status_code == 200:
                    matches = response.json().get('matches', [])
                    if not matches:
                        intel.append("Barcelona fixture telemetry unavailable.")
                    else:
                        match = matches[0]
                        if str(match['homeTeam']['id']) == '81':
                            opponent = match['awayTeam']['name']
                        else:
                            opponent = match['homeTeam']['name']

                        match_dt = datetime.fromisoformat(
                            match['utcDate'].replace('Z', '+00:00')
                        )
                        day = match_dt.day
                        if 11 <= day <= 13:
                            suffix = 'th'
                        else:
                            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(
                                day % 10, 'th'
                            )
                        fixture_date = (
                            match_dt.strftime('%A, %B ')
                            + f"{day}{suffix}"
                        )

                        intel.append(
                            f"Barcelona plays {opponent} on {fixture_date}."
                        )
                else:
                    intel.append("Barcelona fixture telemetry unavailable.")
        except Exception:
            intel.append("Barcelona fixture telemetry unavailable.")

    return " ".join(intel)


if __name__ == "__main__":
    print(f"[SPORTS]: {fetch_sports_data()}")