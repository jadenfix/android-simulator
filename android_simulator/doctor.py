from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass

from .config import default_sdk_root, discover_toolchain, host_memory_mb
from .util import parse_version, run, which


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _java_detail() -> Check:
    java = which("java")
    if not java:
        return Check("Java", False, "missing (bootstrap installs Temurin 21)")
    result = run([java, "-version"], check=False, quiet=True)
    text = (result.stderr or result.stdout).splitlines()
    first = text[0] if text else "version unknown"
    version = parse_version(first)
    return Check("Java", bool(version and version[0] >= 17), first)


def collect_checks() -> list[Check]:
    checks: list[Check] = []
    system = platform.system()
    machine = platform.machine()
    checks.append(Check("macOS", system == "Darwin", f"{system} {platform.mac_ver()[0]}"))
    checks.append(Check("Apple Silicon", machine in {"arm64", "aarch64"}, machine))

    if system == "Darwin":
        try:
            hv = subprocess.check_output(["sysctl", "-n", "kern.hv_support"], text=True).strip()
        except (OSError, subprocess.SubprocessError):
            hv = "unknown"
        checks.append(Check("Hypervisor.framework", hv == "1", hv))

    memory = host_memory_mb()
    checks.append(
        Check(
            "Memory",
            memory is None or memory >= 8192,
            "unknown" if memory is None else f"{memory // 1024} GiB",
        )
    )
    sdk_root = default_sdk_root()
    sdk_root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(sdk_root).free // (1024**3)
    checks.append(Check("Free disk", free_gb >= 20, f"{free_gb} GiB at {sdk_root}"))
    toolchain = discover_toolchain(require_all=False)
    brew = which("brew")
    checks.append(
        Check(
            "Homebrew",
            brew is not None or toolchain is not None,
            str(brew) if brew else "not installed (optional after SDK setup)",
        )
    )
    checks.append(_java_detail())

    if toolchain is None:
        for name in ("sdkmanager", "avdmanager", "adb", "emulator"):
            checks.append(Check(name, False, "missing"))
    else:
        checks.extend(
            [
                Check("sdkmanager", True, str(toolchain.sdkmanager)),
                Check("avdmanager", True, str(toolchain.avdmanager)),
                Check("adb", True, str(toolchain.adb)),
                Check("emulator", True, str(toolchain.emulator)),
            ]
        )
    return checks


def print_doctor() -> bool:
    checks = collect_checks()
    width = max(len(check.name) for check in checks)
    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        print(f"{marker:4}  {check.name:<{width}}  {check.detail}")
    return all(check.ok for check in checks)
