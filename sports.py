import requests
from datetime import datetime


def fetch_sports_root():
    """
    Connects to the Ergast API to retrieve current F1 race data.

    Returns:
        str: A formatted string containing the next F1 race details, 
             or an error message if the connection fails.
    """
    intel = []

    try:
        f1_url = "https://api.jolpi.ca/ergast/f1/current/next.json"
        f1_data = requests.get(f1_url).json()
        race = f1_data['MRData']['RaceTable']['Races'][0]
        intel.append(f"Next F1 Race: {race['raceName']} in {race['Circuit']['Location']['country']} on {race['date']}.")
    except Exception:
        intel.append("F1 race telemetry unavailable.")

    # TODO: Integrate live API for FC Barcelona fixtures
    intel.append("Barcelona's next fixture against Real Madrid. Location: Camp Nou.")

    return " ".join(intel)

if __name__ == "__main__":
    print(fetch_sports_root())