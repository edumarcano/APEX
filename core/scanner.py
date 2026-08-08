import logging
import os
import subprocess
from typing import Literal

import psutil
CPU_THROTTLE_LIMIT = 80.0
RAM_THROTTLE_LIMIT = 85.0
_LOGGER = logging.getLogger(__name__)


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
    except (OSError, subprocess.SubprocessError):
        return None
    return None


PowerState = Literal["plugged", "battery", "unknown"]


def get_power_state() -> PowerState:
    """
    Classify AC/battery presence for advisory preflight.

    Returns:
        ``plugged`` when on AC, ``battery`` when on battery, ``unknown`` when
        no battery sensor is available (typical desktops).
    """
    battery = psutil.sensors_battery()
    if battery is None:
        return "unknown"
    return "plugged" if battery.power_plugged else "battery"


def check_power() -> bool:
    """
    Checks if the computer is plugged in.

    Returns:
        bool: True if plugged in. False when on battery. Desktops with no
        battery sensor return True (unknown is not treated as unplugged).
    """
    return get_power_state() != "battery"


def _bytes_to_gb(value: int | float) -> float:
    """Convert byte count to gigabytes rounded to one decimal place."""
    return round(float(value) / (1024**3), 1)


def sample_system_vitals() -> dict[str, float]:
    """
    Sample CPU, memory, and root-disk utilization with percentages and raw values.

    Each psutil query is isolated; failures fall back to 0.0 and emit
    a diagnostic line for operator visibility.

    Returns:
        Mapping with keys cpu, cpu_freq, ram, ram_used, ram_total, disk,
        disk_used, and disk_total.
    """
    vitals: dict[str, float] = {}

    try:
        vitals["cpu"] = float(psutil.cpu_percent(interval=None))
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.warning("CPU vitals query failed: %s", type(exc).__name__)
        vitals["cpu"] = 0.0

    try:
        freq = psutil.cpu_freq()
        vitals["cpu_freq"] = round(float(freq.current) / 1000.0, 1) if freq else 0.0
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.warning("CPU frequency query failed: %s", type(exc).__name__)
        vitals["cpu_freq"] = 0.0

    try:
        mem = psutil.virtual_memory()
        vitals["ram"] = float(mem.percent)
        vitals["ram_used"] = _bytes_to_gb(mem.used)
        vitals["ram_total"] = _bytes_to_gb(mem.total)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.warning("Memory vitals query failed: %s", type(exc).__name__)
        vitals["ram"] = 0.0
        vitals["ram_used"] = 0.0
        vitals["ram_total"] = 0.0

    try:
        root_path = os.path.abspath(os.sep)
        disk = psutil.disk_usage(root_path)
        vitals["disk"] = float(disk.percent)
        vitals["disk_used"] = _bytes_to_gb(disk.used)
        vitals["disk_total"] = _bytes_to_gb(disk.total)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.warning("Disk vitals query failed: %s", type(exc).__name__)
        vitals["disk"] = 0.0
        vitals["disk_used"] = 0.0
        vitals["disk_total"] = 0.0

    return vitals


def is_system_throttled() -> bool:
    """
    Assess whether CPU or RAM utilization exceeds hardware throttle thresholds.

    RAM is checked first; sustained high CPU requires two sequential samples
    spaced 100ms apart to both exceed the CPU limit.

    Returns:
        bool: True when throttling thresholds are met, False otherwise or on error.
    """
    try:
        try:
            ram_percent = float(psutil.virtual_memory().percent)
        except (OSError, AttributeError, TypeError, ValueError):
            ram_percent = 0.0

        if ram_percent >= RAM_THROTTLE_LIMIT:
            return True

        cpu_sample_1 = float(psutil.cpu_percent(interval=0.1))
        cpu_sample_2 = float(psutil.cpu_percent(interval=0.1))

        return cpu_sample_1 > CPU_THROTTLE_LIMIT and cpu_sample_2 > CPU_THROTTLE_LIMIT
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.warning("Hardware throttle assessment failed: %s", type(exc).__name__)
        return False



if __name__ == "__main__":
    vitals = sample_system_vitals()
    print(
        f"[SCANNER]: Vitals snapshot — CPU: {vitals['cpu']}%, "
        f"RAM: {vitals['ram']}% ({vitals['ram_used']}/{vitals['ram_total']} GB)"
    )
    print(
        f"[SCANNER]: Throttle limits — CPU: {CPU_THROTTLE_LIMIT}%, "
        f"RAM: {RAM_THROTTLE_LIMIT}%"
    )
    throttled = is_system_throttled()
    print(f"[SCANNER]: Hardware throttle active: {throttled}")
