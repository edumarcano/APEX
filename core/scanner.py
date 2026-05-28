import os
import subprocess
from datetime import datetime, timedelta

import psutil
from dotenv import load_dotenv

from core import database
from core.config import ENV_PATH, is_dev_mode

load_dotenv(dotenv_path=ENV_PATH)

COOLDOWN_SECONDS = 3600


def get_current_ssid() -> str | None:
    """
    Gets the current SSID of the wifi connection.
    Returns:
        str: The current SSID, or None if the connection is not found.
    """
    try:
        results = subprocess.check_output(["netsh", "wlan", "show", "interfaces"]).decode("utf-8")
        for line in results.split("\n"):
            if "SSID" in line and "BSSID" not in line:
                return line.split(":", 1)[1].strip()
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


def sample_system_vitals() -> dict[str, float]:
    """
    Sample CPU, memory, and root-disk utilization as percentage floats.

    Each psutil query is isolated; failures fall back to 0.0 and emit
    a diagnostic line for operator visibility.

    Returns:
        Mapping with keys cpu, ram, and disk.
    """
    vitals: dict[str, float] = {}

    try:
        vitals["cpu"] = float(psutil.cpu_percent(interval=None))
    except Exception as exc:
        print(f"[SCANNER]: CPU vitals query failed: {exc}")
        vitals["cpu"] = 0.0

    try:
        vitals["ram"] = float(psutil.virtual_memory().percent)
    except Exception as exc:
        print(f"[SCANNER]: Memory vitals query failed: {exc}")
        vitals["ram"] = 0.0

    try:
        root_path = os.path.abspath(os.sep)
        vitals["disk"] = float(psutil.disk_usage(root_path).percent)
    except Exception as exc:
        print(f"[SCANNER]: Disk vitals query failed: {exc}")
        vitals["disk"] = 0.0

    return vitals


def should_run() -> bool:
    """
    Checks if the computer should run.
    Returns:
        bool: True if the computer should run, False otherwise.
    """
    database.initialize_db()

    if is_dev_mode():
        print(
            "[SCANNER]: DEV_MODE active — bypassing Wi-Fi SSID validation, "
            "AC power connectivity check, and 1-hour execution cooldown."
        )
        return True

    current_wifi = get_current_ssid()
    target_wifi = os.getenv("HOME_SSID")
    is_plugged = check_power()

    # TODO: Implement 'Ambient Mode' to allow limited briefings on untrusted networks.
    if not target_wifi or current_wifi != target_wifi:
        print("[SCANNER]: Checks failed. Unauthorized WiFi connection detected.")
        return False
    # TODO: Implement config-level toggle for flexible deployment.
    if not is_plugged:
        print("[SCANNER]: Checks failed. AC power not detected.")
        return False

    last_successful_run = database.get_last_run()
    cooldown_period = timedelta(seconds=COOLDOWN_SECONDS)

    on_cooldown = (
        last_successful_run
        and (datetime.now() - last_successful_run) < cooldown_period
    )

    # TODO: Transition to hardware debounce logic and user-configurable bypass.
    if on_cooldown:
        print(
            "[SCANNER]: Checks failed. System still on cooldown. "
            f"Time since last run: {datetime.now() - last_successful_run}"
        )
        return False

    return True


if __name__ == "__main__":
    if should_run():
        print("[SCANNER]: Checks passed.")
