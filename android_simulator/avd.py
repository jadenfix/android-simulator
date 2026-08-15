from __future__ import annotations

import platform
import re
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import adb as adb_module
from .config import (
    DEFAULT_ARCH,
    DEVICE_CANDIDATES,
    Toolchain,
    avd_home,
    instance_metadata_path,
    logs_root,
    recommended_ram_mb,
    validate_avd_name,
)
from .errors import AndroidSimError
from .sdk import install_image, resolve_image, sdk_env
from .util import atomic_write, load_json, parse_version, run, save_json


def list_avds(toolchain: Toolchain) -> list[str]:
    result = run([toolchain.emulator, "-list-avds"], quiet=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def list_device_definitions(toolchain: Toolchain) -> list[str]:
    result = run([toolchain.avdmanager, "list", "device", "-c"], env=sdk_env(toolchain), quiet=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def choose_device(toolchain: Toolchain, requested: str | None) -> str:
    available = set(list_device_definitions(toolchain))
    if requested:
        if requested not in available:
            raise AndroidSimError(
                f"Unknown AVD hardware profile {requested!r}. Available IDs include: "
                + ", ".join(sorted(available)[:20])
            )
        return requested
    for candidate in DEVICE_CANDIDATES:
        if candidate in available:
            return candidate
    if available:
        return sorted(available)[0]
    raise AndroidSimError("avdmanager returned no hardware profiles")


def _read_ini(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def _write_ini(path: Path, values: dict[str, str]) -> None:
    content = "".join(f"{key}={values[key]}\n" for key in sorted(values))
    atomic_write(path, content)


def configure_avd(name: str, *, ram_mb: int, data_gb: int, play_store: bool) -> Path:
    config_path = avd_home() / f"{name}.avd" / "config.ini"
    if not config_path.exists():
        raise AndroidSimError(f"AVD config was not created at {config_path}")
    values = _read_ini(config_path)
    values.update(
        {
            "disk.dataPartition.size": f"{data_gb}G",
            "fastboot.forceColdBoot": "no",
            "fastboot.forceFastBoot": "yes",
            "hw.cpu.ncore": "4",
            "hw.gpu.enabled": "yes",
            "hw.gpu.mode": "auto",
            "hw.keyboard": "yes",
            "hw.ramSize": str(ram_mb),
            "sdcard.size": "2048M",
            "showDeviceFrame": "yes",
            "vm.heapSize": "512",
        }
    )
    if play_store:
        values["PlayStore.enabled"] = "true"
    _write_ini(config_path, values)
    return config_path


def create_avd(
    toolchain: Toolchain,
    *,
    name: str,
    profile: str,
    api: int | None,
    arch: str = DEFAULT_ARCH,
    device: str | None = None,
    ram_mb: int | None = None,
    data_gb: int = 16,
    force: bool = False,
) -> dict:
    validate_avd_name(name)
    if platform.system() == "Darwin" and platform.machine() not in {"arm64", "aarch64"}:
        raise AndroidSimError("This setup is optimized for Apple Silicon (arm64), not an Intel Mac")
    existing_avds = list_avds(toolchain)
    if name in existing_avds and not force:
        raise AndroidSimError(f"AVD {name!r} already exists; pass --force to replace it")
    running_serial = _running_serial_for_avd(toolchain, name) if name in existing_avds else None
    if running_serial:
        raise AndroidSimError(
            f"AVD {name!r} is running as {running_serial}; stop it before using --force"
        )
    if data_gb < 8:
        raise AndroidSimError("--data-gb must be at least 8")
    selected_ram = ram_mb or recommended_ram_mb()
    if selected_ram < 2048 or selected_ram > 8192:
        raise AndroidSimError("--ram-mb must be between 2048 and 8192")

    selection = resolve_image(
        toolchain,
        profile=profile,
        requested_api=api,
        arch=arch,
    )
    install_image(toolchain, selection)
    chosen_device = choose_device(toolchain, device)
    command = [
        toolchain.avdmanager,
        "create",
        "avd",
        "-n",
        name,
        "-k",
        selection.package,
        "-d",
        chosen_device,
        "-f",
    ]
    run(command, input_text="no\n", env=sdk_env(toolchain), capture=False)
    config_path = configure_avd(
        name,
        ram_mb=selected_ram,
        data_gb=data_gb,
        play_store=profile == "play",
    )
    metadata = {
        "name": name,
        "profile": profile,
        "api": selection.api,
        "arch": selection.arch,
        "image_package": selection.package,
        "device_profile": chosen_device,
        "ram_mb": selected_ram,
        "data_gb": data_gb,
        "instance_uuid": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
    }
    save_json(instance_metadata_path(name), metadata)
    return metadata


def delete_avd(toolchain: Toolchain, name: str) -> None:
    validate_avd_name(name)
    running_serial = _running_serial_for_avd(toolchain, name)
    if running_serial:
        stop_device(toolchain, running_serial)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if all(device.serial != running_serial for device in adb_module.list_devices(toolchain)):
                break
            time.sleep(1)
        else:
            raise AndroidSimError(f"Timed out waiting for {running_serial} to stop before deletion")
    run([toolchain.avdmanager, "delete", "avd", "-n", name], env=sdk_env(toolchain))
    instance_metadata_path(name).unlink(missing_ok=True)


def load_metadata(name: str) -> dict:
    validate_avd_name(name)
    return load_json(instance_metadata_path(name))


def create_fresh_identity(
    toolchain: Toolchain,
    source_name: str,
    new_name: str | None,
) -> dict:
    source = load_metadata(source_name)
    if new_name:
        name = new_name
    else:
        base = source_name[:71].rstrip("._-") or "android-sim"
        name = f"{base}-{uuid.uuid4().hex[:8]}"
    return create_avd(
        toolchain,
        name=name,
        profile=str(source["profile"]),
        api=int(source["api"]),
        arch=str(source.get("arch", DEFAULT_ARCH)),
        device=str(source["device_profile"]),
        ram_mb=int(source["ram_mb"]),
        data_gb=int(source["data_gb"]),
        force=False,
    )


def emulator_version(toolchain: Toolchain) -> tuple[int, ...]:
    result = run([toolchain.emulator, "-version"], check=False, quiet=True)
    return parse_version(result.stdout + "\n" + result.stderr)


def _used_ports(toolchain: Toolchain) -> set[int]:
    ports: set[int] = set()
    for device in adb_module.list_devices(toolchain):
        match = re.fullmatch(r"emulator-(\d+)", device.serial)
        if match:
            ports.add(int(match.group(1)))
    return ports


def choose_port(toolchain: Toolchain) -> int:
    used = _used_ports(toolchain)
    for port in range(5554, 5683, 2):
        if port not in used:
            return port
    raise AndroidSimError("All Android Emulator console ports from 5554 through 5682 are occupied")


def _wifi_netsim_args(ssid: str, password: str | None) -> str:
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise AndroidSimError("Wi-Fi SSID must be 1-32 bytes")
    if any(character in ssid for character in "\r\n\x00"):
        raise AndroidSimError("Wi-Fi SSID contains an unsupported control character")
    values = ["--wifi", ssid]
    if password is not None:
        if not 8 <= len(password) <= 63:
            raise AndroidSimError("Wi-Fi password must be 8-63 characters")
        if any(character in password for character in "\r\n\x00"):
            raise AndroidSimError("Wi-Fi password contains an unsupported control character")
        values.append(password)
    return shlex.join(values)


def start_avd(
    toolchain: Toolchain,
    *,
    name: str,
    cold: bool = False,
    wipe: bool = False,
    headless: bool = False,
    no_audio: bool = False,
    wifi_ssid: str | None = None,
    wifi_password: str | None = None,
    dns_servers: str | None = None,
    proxy: str | None = None,
    wait: bool = True,
    timeout_seconds: int = 240,
    extra_args: list[str] | None = None,
) -> str:
    validate_avd_name(name)
    if name not in list_avds(toolchain):
        raise AndroidSimError(f"AVD {name!r} does not exist. Run 'android-sim create' first.")
    if wifi_password and not wifi_ssid:
        raise AndroidSimError("--wifi-password requires --wifi-ssid")
    version = emulator_version(toolchain)
    if wifi_ssid and version and version < (36, 5):
        raise AndroidSimError(
            "Custom Wi-Fi SSIDs require Android Emulator 36.5 or newer; run 'android-sim update-sdk'"
        )

    port = choose_port(toolchain)
    serial = f"emulator-{port}"
    command = [
        str(toolchain.emulator),
        "-avd",
        name,
        "-port",
        str(port),
        "-gpu",
        "auto",
    ]
    if cold:
        command.append("-no-snapshot-load")
    if wipe:
        command.append("-wipe-data")
    if headless:
        command.extend(["-no-window", "-no-boot-anim"])
    if no_audio:
        command.append("-no-audio")
    if wifi_ssid:
        command.append(f"-netsim-args={_wifi_netsim_args(wifi_ssid, wifi_password)}")
    if dns_servers:
        command.extend(["-dns-server", dns_servers])
    if proxy:
        command.extend(["-http-proxy", proxy])
    if extra_args:
        command.extend(extra_args)

    log_dir = logs_root()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}-{port}.log"
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=sdk_env(toolchain),
        )
    time.sleep(0.5)
    returncode = process.poll()
    if returncode is not None:
        tail = ""
        try:
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
        except OSError:
            pass
        raise AndroidSimError(
            f"Android Emulator exited immediately with status {returncode}. Log: {log_path}"
            + (f"\n{tail}" if tail else "")
        )
    if wait:
        try:
            adb_module.wait_for_boot(toolchain, serial, timeout_seconds=timeout_seconds)
        except AndroidSimError as exc:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            raise AndroidSimError(f"{exc}\nEmulator log: {log_path}") from exc
        # Ensure simulated Wi-Fi is enabled after the framework is ready.
        adb_module.shell(toolchain, serial, ["svc", "wifi", "enable"], check=False, quiet=True)
    print(f"Started {name} as {serial}")
    print(f"Emulator log: {log_path}")
    return serial


def stop_device(toolchain: Toolchain, serial: str) -> None:
    result = adb_module.adb(toolchain, serial, ["emu", "kill"], check=False)
    if result.returncode != 0:
        raise AndroidSimError(result.stderr.strip() or f"Failed to stop {serial}")


def _running_serial_for_avd(toolchain: Toolchain, name: str) -> str | None:
    for device in adb_module.list_devices(toolchain):
        if not device.serial.startswith("emulator-") or device.state != "device":
            continue
        running_name = adb_module.emulator_avd_name(toolchain, device.serial)
        if running_name == name:
            return device.serial
    return None


def reset_identity(toolchain: Toolchain, name: str, *, wait: bool = True) -> str:
    """Factory-reset an AVD by stopping it and booting once with -wipe-data."""
    running_serial = _running_serial_for_avd(toolchain, name)
    if running_serial:
        stop_device(toolchain, running_serial)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if all(device.serial != running_serial for device in adb_module.list_devices(toolchain)):
                break
            time.sleep(1)
        else:
            raise AndroidSimError(f"Timed out waiting for {running_serial} to stop before reset")
    serial = start_avd(toolchain, name=name, wipe=True, cold=True, wait=wait)
    metadata_path = instance_metadata_path(name)
    if metadata_path.exists():
        metadata = load_json(metadata_path)
        metadata["instance_uuid"] = str(uuid.uuid4())
        metadata["reset_at"] = datetime.now(timezone.utc).isoformat()
        save_json(metadata_path, metadata)
    return serial
