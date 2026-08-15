from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .config import Toolchain, instance_metadata_path
from .errors import AndroidSimError
from .util import Result, load_json, run


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    details: str


def list_devices(toolchain: Toolchain) -> list[Device]:
    result = run([toolchain.adb, "devices", "-l"], quiet=True)
    devices: list[Device] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=2)
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "unknown"
        details = parts[2] if len(parts) > 2 else ""
        devices.append(Device(serial=serial, state=state, details=details))
    return devices


def select_device(toolchain: Toolchain, serial: str | None = None) -> Device:
    devices = [device for device in list_devices(toolchain) if device.state == "device"]
    if serial:
        for device in devices:
            if device.serial == serial:
                return device
        raise AndroidSimError(f"ADB device {serial!r} is not connected and ready")
    emulators = [device for device in devices if device.serial.startswith("emulator-")]
    if len(emulators) == 1:
        return emulators[0]
    if not emulators:
        raise AndroidSimError("No running Android emulator found. Run 'android-sim start' first.")
    raise AndroidSimError(
        "Multiple emulators are running; pass --serial with one of: "
        + ", ".join(device.serial for device in emulators)
    )


def adb(
    toolchain: Toolchain,
    serial: str,
    args: Sequence[str | Path],
    *,
    check: bool = True,
    capture: bool = True,
    quiet: bool = False,
) -> Result:
    return run(
        [toolchain.adb, "-s", serial, *args],
        check=check,
        capture=capture,
        quiet=quiet,
    )


def shell(
    toolchain: Toolchain,
    serial: str,
    args: Sequence[str],
    *,
    check: bool = True,
    quiet: bool = False,
) -> str:
    return adb(
        toolchain,
        serial,
        ["shell", *args],
        check=check,
        quiet=quiet,
    ).stdout.strip()


def wait_for_boot(toolchain: Toolchain, serial: str, timeout_seconds: int = 240) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        connected = next(
            (device for device in list_devices(toolchain) if device.serial == serial),
            None,
        )
        if connected is not None and connected.state == "device":
            break
        time.sleep(1)
    else:
        raise AndroidSimError(
            f"Emulator {serial} did not appear in ADB within {timeout_seconds}s"
        )

    while time.monotonic() < deadline:
        boot = shell(
            toolchain,
            serial,
            ["getprop", "sys.boot_completed"],
            check=False,
            quiet=True,
        )
        animation = shell(
            toolchain,
            serial,
            ["getprop", "init.svc.bootanim"],
            check=False,
            quiet=True,
        )
        if boot == "1" and animation in {"stopped", ""}:
            # Confirm package manager is responsive before returning.
            probe = adb(
                toolchain,
                serial,
                ["shell", "cmd", "package", "list", "packages", "android"],
                check=False,
                quiet=True,
            )
            if probe.returncode == 0:
                return
        time.sleep(2)
    raise AndroidSimError(f"Emulator {serial} did not finish booting within {timeout_seconds}s")


def emulator_avd_name(toolchain: Toolchain, serial: str) -> str:
    """Return the configured AVD name for a running emulator.

    Newer emulator builds expose the name through a boot property. Some older
    or transitional builds leave that property empty, so fall back to the
    emulator console command.
    """
    name = shell(
        toolchain,
        serial,
        ["getprop", "ro.boot.qemu.avd_name"],
        check=False,
        quiet=True,
    )
    if name:
        return name

    result = adb(
        toolchain,
        serial,
        ["emu", "avd", "name"],
        check=False,
        quiet=True,
    )
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if candidate and candidate != "OK":
            return candidate
    return ""


def identity(toolchain: Toolchain, serial: str) -> dict[str, str]:
    commands = {
        "secure_android_id_for_shell": ["settings", "get", "secure", "android_id"],
        "build_fingerprint": ["getprop", "ro.build.fingerprint"],
        "model": ["getprop", "ro.product.model"],
        "manufacturer": ["getprop", "ro.product.manufacturer"],
        "android_release": ["getprop", "ro.build.version.release"],
        "api_level": ["getprop", "ro.build.version.sdk"],
        "abi": ["getprop", "ro.product.cpu.abi"],
        "boot_serial": ["getprop", "ro.boot.serialno"],
    }
    values = {
        key: shell(toolchain, serial, command, check=False, quiet=True)
        for key, command in commands.items()
    }
    values["avd_name"] = emulator_avd_name(toolchain, serial)
    values["adb_serial"] = serial
    avd_name = values.get("avd_name", "")
    metadata_path = instance_metadata_path(avd_name) if avd_name else None
    if metadata_path and metadata_path.exists():
        metadata = load_json(metadata_path)
        values["host_instance_uuid"] = str(metadata.get("instance_uuid", ""))
    return values


def print_identity(toolchain: Toolchain, serial: str, as_json: bool = False) -> None:
    values = identity(toolchain, serial)
    if as_json:
        print(json.dumps(values, indent=2, sort_keys=True))
        return
    width = max(len(key) for key in values)
    for key, value in values.items():
        print(f"{key:<{width}}  {value}")


def install_apks(
    toolchain: Toolchain,
    serial: str,
    paths: Iterable[Path],
    *,
    replace: bool,
    grant: bool,
    test_only: bool,
) -> None:
    apks = [path.expanduser().resolve() for path in paths]
    if not apks:
        raise AndroidSimError("No APK files were provided")
    for apk in apks:
        if not apk.is_file():
            raise AndroidSimError(f"APK file not found: {apk}")
        if apk.suffix.lower() != ".apk":
            raise AndroidSimError(f"Expected an .apk file: {apk}")
    args: list[str | Path] = ["install" if len(apks) == 1 else "install-multiple"]
    if replace:
        args.append("-r")
    if grant:
        args.append("-g")
    if test_only:
        args.append("-t")
    args.extend(apks)
    adb(toolchain, serial, args, capture=False)
