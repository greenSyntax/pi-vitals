import re
import subprocess
from typing import Optional

THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"

# Bit meanings of `vcgencmd get_throttled`
THROTTLE_FLAGS = {
    0: "under_voltage",
    1: "freq_capped",
    2: "throttled",
    3: "soft_temp_limit",
    16: "under_voltage_occurred",
    17: "freq_capped_occurred",
    18: "throttled_occurred",
    19: "soft_temp_limit_occurred",
}


def read_temperature(path: str = THERMAL_PATH) -> Optional[float]:
    try:
        with open(path) as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def parse_throttled(output: str) -> Optional[dict]:
    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", output)
    if not match:
        return None
    value = int(match.group(1), 16)
    flags = {name: bool(value & (1 << bit)) for bit, name in THROTTLE_FLAGS.items()}
    return {"raw": match.group(1), **flags}


def read_throttled() -> Optional[dict]:
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_throttled(result.stdout)


def collect() -> dict:
    return {
        "temperature_c": read_temperature(),
        "throttling": read_throttled(),
    }
