import psutil
import subprocess
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import database
import speaker

load_dotenv()


def get_current_ssid():
    """
    Gets the current SSID of the wifi connection.
    Returns:
        str: The current SSID, or None if the connection is not found.
    """
    try:
        results = subprocess.check_output(["netsh", "wlan", "show", "interfaces"]).decode("utf-8")
        for line in results.split("\n"):
            if "SSID" in line and "BSSID" not in line:
                return line.split(":")[1].strip()
    except Exception:
        return None
    return None


def check_power() -> bool:
    """
    Checks if the computer is plugged in.
    Returns:
        bool: True if the computer is plugged in, False otherwise.
    """
    battery = psutil.sensors_battery()
    return battery.power_plugged if battery else False


def should_run() -> bool:
    """
    Checks if the computer should run.
    Returns:
        bool: True if the computer should run, False otherwise.
    """
    database.initialize_db() 

    SHOWCASE_MODE = os.getenv("SHOWCASE_MODE", "false").lower()
    if SHOWCASE_MODE == "true":
        print("[SCANNER]: Showcase mode enabled. Bypassing all checks.")
        return True
    
    current_wifi = get_current_ssid()
    target_wifi = os.getenv("HOME_SSID")
    is_plugged = check_power()
    
    if not current_wifi == target_wifi:
        print("[SCANNER]: Checks failed. Unauthorized WiFi connection detected.")
        return False
    if not is_plugged:
        print("[SCANNER]: Checks failed. AC power not detected.")
        return False

    TEST_MODE = os.getenv("TEST_MODE", "false").lower()
    if TEST_MODE == "true":
        print("[SCANNER]: Test mode enabled. Bypassing cooldown.")
        return True

    last_run = database.get_last_run()
    cooldown_period = timedelta(hours=6)
    
    on_cooldown = last_run and (datetime.now() - last_run) < cooldown_period

    if on_cooldown:
        print(
            "[SCANNER]: Checks failed. System still on cooldown. "
            f"Time since last run: {datetime.now() - last_run}"
        )
        return False

    return True

if __name__ == "__main__":
    if should_run():
        print("[SCANNER]: Checks passed.")