from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import AndroidSimError
from .util import which

DEFAULT_API_CANDIDATES = (37, 36, 35)
DEFAULT_ARCH = "arm64-v8a"
DEFAULT_NAME = "android-sim-play"

PROFILE_TAGS = {
    "play": "google_apis_playstore",
    "google": "google_apis",
    "aosp": "default",
}

DEVICE_CANDIDATES = (
    "pixel_9",
    "pixel_8",
    "pixel_7",
    "pixel_6",
    "pixel_5",
    "pixel",
)


@dataclass(frozen=True)
class Toolchain:
    sdk_root: Path
    sdkmanager: Path
    avdmanager: Path
    adb: Path
    emulator: Path


def default_sdk_root() -> Path:
    explicit = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if platform.system() == "Darwin":
        return (Path.home() / "Library" / "Android" / "sdk").resolve()
    return (Path.home() / "Android" / "Sdk").resolve()


def state_root() -> Path:
    explicit = os.environ.get("ANDROID_SIM_HOME")
    return Path(explicit).expanduser().resolve() if explicit else Path.home() / ".android-simulator"


def instance_metadata_path(name: str) -> Path:
    return state_root() / "instances" / f"{name}.json"


def logs_root() -> Path:
    return state_root() / "logs"


def avd_home() -> Path:
    explicit = os.environ.get("ANDROID_AVD_HOME")
    return Path(explicit).expanduser().resolve() if explicit else Path.home() / ".android" / "avd"


def validate_avd_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
        raise AndroidSimError(
            "AVD name must be 1-80 characters using letters, digits, dot, underscore, or hyphen"
        )
    return name


def image_package(api: int, profile: str, arch: str = DEFAULT_ARCH) -> str:
    try:
        tag = PROFILE_TAGS[profile]
    except KeyError as exc:
        raise AndroidSimError(
            f"Unknown profile {profile!r}; choose one of: {', '.join(PROFILE_TAGS)}"
        ) from exc
    return f"system-images;android-{api};{tag};{arch}"


def host_memory_mb() -> int | None:
    try:
        if platform.system() == "Darwin":
            output = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return int(output) // (1024 * 1024)
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size) // (1024 * 1024)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def recommended_ram_mb() -> int:
    host = host_memory_mb()
    if host is None:
        return 4096
    if host >= 32768:
        return 6144
    if host >= 16384:
        return 4096
    return 3072


def _tool_candidates(sdk_root: Path, tool: str) -> list[Path]:
    candidates = [
        sdk_root / "platform-tools" / tool,
        sdk_root / "emulator" / tool,
        sdk_root / "cmdline-tools" / "latest" / "bin" / tool,
    ]
    cmdline_root = sdk_root / "cmdline-tools"
    if cmdline_root.is_dir():
        for directory in sorted(cmdline_root.iterdir(), reverse=True):
            candidates.append(directory / "bin" / tool)

    # Homebrew's command-line-tools cask defaults to this separate SDK root.
    for prefix in (Path("/opt/homebrew"), Path("/usr/local")):
        candidates.extend(
            [
                prefix / "bin" / tool,
                prefix / "share" / "android-commandlinetools" / "cmdline-tools" / "latest" / "bin" / tool,
                prefix / "share" / "android-commandlinetools" / "cmdline-tools" / "bin" / tool,
            ]
        )
    return candidates


def discover_toolchain(require_all: bool = True) -> Toolchain | None:
    sdk_root = default_sdk_root()
    tools = {
        name: which(name, _tool_candidates(sdk_root, name))
        for name in ("sdkmanager", "avdmanager", "adb", "emulator")
    }
    missing = [name for name, path in tools.items() if path is None]
    if missing:
        if not require_all:
            return None
        raise AndroidSimError(
            "Missing Android SDK tools: "
            + ", ".join(missing)
            + ". Run ./scripts/bootstrap-macos.sh first."
        )
    return Toolchain(
        sdk_root=sdk_root,
        sdkmanager=tools["sdkmanager"],  # type: ignore[arg-type]
        avdmanager=tools["avdmanager"],  # type: ignore[arg-type]
        adb=tools["adb"],  # type: ignore[arg-type]
        emulator=tools["emulator"],  # type: ignore[arg-type]
    )
