import json
import os
import requests
from dotenv import load_dotenv
from datetime import datetime
from core.config import MODULE_FOOTBALL, MODULE_F1

load_dotenv()


def fetch_sports_data() -> str:
    """
    Connect to sports APIs and retrieve current sports telemetry.

    Returns:
        str: A formatted string containing sports updates, or error
        messages if connections fail.
    """
    intel = []

    if MODULE_F1:
        try:
            f1_url = "https://api.jolpi.ca/ergast/f1/current/next.json"
            f1_data = requests.get(f1_url, timeout=10).json()
            race = f1_data['MRData']['RaceTable']['Races'][0]
            intel.append(
                f"Next F1 Race: {race['raceName']} in "
                f"{race['Circuit']['Location']['country']} on {race['date']}."
            )
        except Exception:
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