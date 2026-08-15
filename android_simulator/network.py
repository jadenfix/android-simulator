from __future__ import annotations

import re

from . import adb as adb_module
from .config import Toolchain
from .errors import AndroidSimError

SPEEDS = {"full", "gsm", "hscsd", "gprs", "edge", "umts", "hsdpa", "lte", "evdo"}
DELAYS = {"none", "gprs", "edge", "umts"}


def wifi(toolchain: Toolchain, serial: str, enabled: bool) -> None:
    adb_module.shell(toolchain, serial, ["svc", "wifi", "enable" if enabled else "disable"])


def status(toolchain: Toolchain, serial: str) -> dict[str, str]:
    return {
        "wifi_enabled": adb_module.shell(
            toolchain, serial, ["settings", "get", "global", "wifi_on"], check=False, quiet=True
        ),
        "wifi_interface": adb_module.shell(
            toolchain, serial, ["ip", "address", "show", "wlan0"], check=False, quiet=True
        ),
        "ethernet_interface": adb_module.shell(
            toolchain, serial, ["ip", "address", "show", "eth0"], check=False, quiet=True
        ),
        "default_route": adb_module.shell(
            toolchain, serial, ["ip", "route", "show", "default"], check=False, quiet=True
        ),
        "http_proxy": adb_module.shell(
            toolchain, serial, ["settings", "get", "global", "http_proxy"], check=False, quiet=True
        ),
    }


def set_speed(toolchain: Toolchain, serial: str, speed: str) -> None:
    if speed not in SPEEDS:
        raise AndroidSimError(f"Unknown speed {speed!r}; choose one of: {', '.join(sorted(SPEEDS))}")
    adb_module.adb(toolchain, serial, ["emu", "network", "speed", speed], capture=False)


def set_delay(toolchain: Toolchain, serial: str, delay: str) -> None:
    if delay not in DELAYS:
        raise AndroidSimError(f"Unknown delay {delay!r}; choose one of: {', '.join(sorted(DELAYS))}")
    adb_module.adb(toolchain, serial, ["emu", "network", "delay", delay], capture=False)


def set_proxy(toolchain: Toolchain, serial: str, proxy: str) -> None:
    if not re.fullmatch(r"[^:\s]+:\d{1,5}", proxy):
        raise AndroidSimError("Proxy must be in host:port form")
    port = int(proxy.rsplit(":", 1)[1])
    if port > 65535:
        raise AndroidSimError("Proxy port must be <= 65535")
    adb_module.shell(toolchain, serial, ["settings", "put", "global", "http_proxy", proxy])


def clear_proxy(toolchain: Toolchain, serial: str) -> None:
    adb_module.shell(toolchain, serial, ["settings", "put", "global", "http_proxy", ":0"])
