from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from . import adb as adb_module
from .config import Toolchain
from .errors import AndroidSimError
from .util import download, safe_download_name


def collect_apks(paths: list[Path]) -> list[Path]:
    collected: list[Path] = []
    for path in paths:
        expanded = path.expanduser().resolve()
        if expanded.is_dir():
            collected.extend(sorted(expanded.glob("*.apk")))
        elif expanded.suffix.lower() == ".apk":
            collected.append(expanded)
        elif expanded.suffix.lower() == ".apks":
            raise AndroidSimError(
                f"{expanded.name} is an Android App Bundle archive. Use bundletool to select device-specific splits, "
                "or provide the extracted APK split directory."
            )
        else:
            raise AndroidSimError(f"Expected an APK file or directory of APK splits: {expanded}")
    return collected


def install_local(
    toolchain: Toolchain,
    serial: str,
    paths: list[Path],
    *,
    replace: bool = True,
    grant: bool = True,
    test_only: bool = False,
) -> None:
    apks = collect_apks(paths)
    adb_module.install_apks(
        toolchain,
        serial,
        apks,
        replace=replace,
        grant=grant,
        test_only=test_only,
    )


def install_url(
    toolchain: Toolchain,
    serial: str,
    url: str,
    *,
    sha256: str | None,
    allow_http: bool,
    replace: bool,
    grant: bool,
    test_only: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="android-sim-") as temp_dir:
        name = safe_download_name(url, fallback="download.apk")
        if not name.lower().endswith(".apk"):
            name += ".apk"
        target = Path(temp_dir) / name
        download(url, target, expected_sha256=sha256, allow_http=allow_http)
        install_local(
            toolchain,
            serial,
            [target],
            replace=replace,
            grant=grant,
            test_only=test_only,
        )


def push_download(
    toolchain: Toolchain,
    serial: str,
    url: str,
    *,
    sha256: str | None,
    allow_http: bool,
    filename: str | None,
) -> str:
    with tempfile.TemporaryDirectory(prefix="android-sim-") as temp_dir:
        name = filename or safe_download_name(url)
        if (
            not name
            or name in {".", ".."}
            or any(character in name for character in "/\\\r\n\x00")
            or len(name.encode("utf-8")) > 180
        ):
            raise AndroidSimError("--filename must be a safe plain filename up to 180 bytes")
        target = Path(temp_dir) / name
        download(url, target, expected_sha256=sha256, allow_http=allow_http)
        remote = f"/sdcard/Download/{name}"
        adb_module.adb(toolchain, serial, ["push", target, remote], capture=False)
        adb_module.shell(
            toolchain,
            serial,
            ["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote}"],
            check=False,
            quiet=True,
        )
        return remote


def open_play_store(toolchain: Toolchain, serial: str, package: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package):
        raise AndroidSimError("Invalid Android package name")
    result = adb_module.adb(
        toolchain,
        serial,
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            f"market://details?id={quote(package, safe='._')}",
        ],
        check=False,
    )
    if result.returncode != 0 or "Error" in (result.stdout + result.stderr):
        adb_module.adb(
            toolchain,
            serial,
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                f"https://play.google.com/store/apps/details?id={quote(package, safe='._')}",
            ],
            capture=False,
        )


def launch_package(toolchain: Toolchain, serial: str, package: str) -> None:
    result = adb_module.adb(
        toolchain,
        serial,
        ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        check=False,
    )
    if result.returncode != 0 or "No activities found" in result.stdout + result.stderr:
        raise AndroidSimError(f"Could not find a launcher activity for {package}")


def uninstall_package(toolchain: Toolchain, serial: str, package: str, keep_data: bool) -> None:
    args = ["uninstall"]
    if keep_data:
        args.append("-k")
    args.append(package)
    adb_module.adb(toolchain, serial, args, capture=False)


def list_apps(toolchain: Toolchain, serial: str, third_party: bool) -> list[str]:
    args = ["pm", "list", "packages"]
    if third_party:
        args.append("-3")
    output = adb_module.shell(toolchain, serial, args)
    return sorted(line.removeprefix("package:") for line in output.splitlines() if line)
