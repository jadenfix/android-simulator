from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import adb as adb_module
from . import apps, avd, network
from .config import DEFAULT_ARCH, DEFAULT_NAME, PROFILE_TAGS, discover_toolchain
from .doctor import print_doctor
from .errors import AndroidSimError
from .sdk import install_base_packages, list_packages


def _add_serial(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--serial",
        default=os.environ.get("ANDROID_SIM_SERIAL"),
        help="ADB serial (defaults to the only running emulator)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android-sim",
        description="Reproducible Android Emulator environments for Apple Silicon Macs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check the Mac and Android SDK prerequisites")
    sub.add_parser("update-sdk", help="Install/update emulator, platform-tools, and command-line tools")
    sub.add_parser("images", help="List available ARM64 Android system images")
    sub.add_parser("list", help="List configured AVDs and connected devices")

    create = sub.add_parser("create", help="Create a new isolated Android virtual device")
    create.add_argument("--name", default=DEFAULT_NAME)
    create.add_argument("--profile", choices=sorted(PROFILE_TAGS), default="play")
    create.add_argument("--api", type=int, help="Android API level; defaults to newest supported stable candidate")
    create.add_argument("--arch", default=DEFAULT_ARCH)
    create.add_argument("--device", help="avdmanager hardware profile ID, such as pixel_8")
    create.add_argument("--ram-mb", type=int)
    create.add_argument("--data-gb", type=int, default=16)
    create.add_argument("--force", action="store_true", help="Replace an existing AVD with this name")

    start = sub.add_parser("start", help="Start an AVD and wait for Android to boot")
    start.add_argument("name", nargs="?", default=DEFAULT_NAME)
    start.add_argument("--cold", action="store_true", help="Ignore saved quick-boot snapshots")
    start.add_argument("--wipe", action="store_true", help="Factory reset before booting (destructive)")
    start.add_argument("--headless", action="store_true")
    start.add_argument("--no-audio", action="store_true")
    start.add_argument("--wifi-ssid", help="Custom simulated Wi-Fi SSID (Emulator 36.5+)")
    start.add_argument("--wifi-password", help="Optional WPA2 password; at least 8 characters")
    start.add_argument("--dns", help="Comma-separated DNS servers")
    start.add_argument("--proxy", help="Startup HTTP proxy URL or host:port")
    start.add_argument("--no-wait", action="store_true")
    start.add_argument("--timeout", type=int, default=240)
    start.add_argument(
        "--emulator-arg",
        action="append",
        default=[],
        help="Advanced: append one raw Android Emulator argument (repeatable)",
    )

    stop = sub.add_parser("stop", help="Stop a running emulator")
    _add_serial(stop)

    delete = sub.add_parser("delete", help="Delete an AVD and its persistent data")
    delete.add_argument("name")

    identity = sub.add_parser("identity", help="Show the current emulator identity diagnostics")
    _add_serial(identity)
    identity.add_argument("--json", action="store_true")

    fresh = sub.add_parser(
        "new-identity",
        help="Create a separate fresh AVD identity from an existing managed instance",
    )
    fresh.add_argument("source", nargs="?", default=DEFAULT_NAME)
    fresh.add_argument("--name")

    reset = sub.add_parser(
        "factory-reset",
        help="Wipe an AVD, clearing apps/accounts and generating fresh device state",
    )
    reset.add_argument("name", nargs="?", default=DEFAULT_NAME)
    reset.add_argument("--yes", action="store_true")
    reset.add_argument("--no-wait", action="store_true")

    install = sub.add_parser("install", help="Install one APK or a directory of split APKs")
    _add_serial(install)
    install.add_argument("paths", nargs="+", type=Path)
    install.add_argument("--no-replace", action="store_true")
    install.add_argument("--no-grant", action="store_true")
    install.add_argument("--test-only", action="store_true")

    install_url = sub.add_parser("install-url", help="Download an APK over HTTPS and install it")
    _add_serial(install_url)
    install_url.add_argument("url")
    install_url.add_argument("--sha256")
    install_url.add_argument("--allow-http", action="store_true")
    install_url.add_argument("--no-replace", action="store_true")
    install_url.add_argument("--no-grant", action="store_true")
    install_url.add_argument("--test-only", action="store_true")

    download = sub.add_parser("download", help="Download a file and place it in Android's Downloads folder")
    _add_serial(download)
    download.add_argument("url")
    download.add_argument("--filename")
    download.add_argument("--sha256")
    download.add_argument("--allow-http", action="store_true")

    play = sub.add_parser("play", help="Open an app listing in the official Google Play Store")
    _add_serial(play)
    play.add_argument("package", help="Android package name, for example com.spotify.music")

    launch = sub.add_parser("launch", help="Launch an installed package's main activity")
    _add_serial(launch)
    launch.add_argument("package")

    uninstall = sub.add_parser("uninstall", help="Uninstall a package")
    _add_serial(uninstall)
    uninstall.add_argument("package")
    uninstall.add_argument("--keep-data", action="store_true")

    app_list = sub.add_parser("apps", help="List installed app package names")
    _add_serial(app_list)
    app_list.add_argument("--all", action="store_true", help="Include system packages")

    shell_parser = sub.add_parser("shell", help="Run an adb shell command on the emulator")
    _add_serial(shell_parser)
    shell_parser.add_argument("args", nargs=argparse.REMAINDER)

    network_parser = sub.add_parser("network", help="Inspect or control simulated networking")
    _add_serial(network_parser)
    network_sub = network_parser.add_subparsers(dest="network_command", required=True)
    network_sub.add_parser("status")
    wifi = network_sub.add_parser("wifi")
    wifi.add_argument("state", choices=("on", "off"))
    speed = network_sub.add_parser("speed")
    speed.add_argument("preset")
    delay = network_sub.add_parser("delay")
    delay.add_argument("preset")
    proxy = network_sub.add_parser("proxy")
    proxy.add_argument("value", help="host:port or 'clear'")

    return parser


def _toolchain():
    return discover_toolchain(require_all=True)



def command_main(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        return 0 if print_doctor() else 1

    toolchain = _toolchain()

    if args.command == "update-sdk":
        install_base_packages(toolchain)
        return 0
    if args.command == "images":
        for package in sorted(
            package
            for package in list_packages(toolchain)
            if package.startswith("system-images;") and package.endswith(";arm64-v8a")
        ):
            print(package)
        return 0
    if args.command == "list":
        print("AVDs:")
        for name in avd.list_avds(toolchain):
            print(f"  {name}")
        print("Connected devices:")
        for device in adb_module.list_devices(toolchain):
            print(f"  {device.serial:<16} {device.state:<12} {device.details}")
        return 0
    if args.command == "create":
        metadata = avd.create_avd(
            toolchain,
            name=args.name,
            profile=args.profile,
            api=args.api,
            arch=args.arch,
            device=args.device,
            ram_mb=args.ram_mb,
            data_gb=args.data_gb,
            force=args.force,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True))
        return 0
    if args.command == "start":
        avd.start_avd(
            toolchain,
            name=args.name,
            cold=args.cold,
            wipe=args.wipe,
            headless=args.headless,
            no_audio=args.no_audio,
            wifi_ssid=args.wifi_ssid,
            wifi_password=args.wifi_password,
            dns_servers=args.dns,
            proxy=args.proxy,
            wait=not args.no_wait,
            timeout_seconds=args.timeout,
            extra_args=args.emulator_arg,
        )
        return 0
    if args.command == "stop":
        serial = adb_module.select_device(toolchain, args.serial).serial
        avd.stop_device(toolchain, serial)
        return 0
    if args.command == "delete":
        avd.delete_avd(toolchain, args.name)
        return 0
    if args.command == "identity":
        serial = adb_module.select_device(toolchain, args.serial).serial
        adb_module.print_identity(toolchain, serial, as_json=args.json)
        return 0
    if args.command == "new-identity":
        metadata = avd.create_fresh_identity(toolchain, args.source, args.name)
        print(json.dumps(metadata, indent=2, sort_keys=True))
        return 0
    if args.command == "factory-reset":
        if not args.yes:
            raise AndroidSimError(
                "Factory reset deletes every app, account, and setting in the AVD. Re-run with --yes."
            )
        avd.reset_identity(toolchain, args.name, wait=not args.no_wait)
        return 0
    if args.command == "install":
        serial = adb_module.select_device(toolchain, args.serial).serial
        apps.install_local(
            toolchain,
            serial,
            args.paths,
            replace=not args.no_replace,
            grant=not args.no_grant,
            test_only=args.test_only,
        )
        return 0
    if args.command == "install-url":
        serial = adb_module.select_device(toolchain, args.serial).serial
        apps.install_url(
            toolchain,
            serial,
            args.url,
            sha256=args.sha256,
            allow_http=args.allow_http,
            replace=not args.no_replace,
            grant=not args.no_grant,
            test_only=args.test_only,
        )
        return 0
    if args.command == "download":
        serial = adb_module.select_device(toolchain, args.serial).serial
        remote = apps.push_download(
            toolchain,
            serial,
            args.url,
            sha256=args.sha256,
            allow_http=args.allow_http,
            filename=args.filename,
        )
        print(remote)
        return 0
    if args.command == "play":
        serial = adb_module.select_device(toolchain, args.serial).serial
        apps.open_play_store(toolchain, serial, args.package)
        return 0
    if args.command == "launch":
        serial = adb_module.select_device(toolchain, args.serial).serial
        apps.launch_package(toolchain, serial, args.package)
        return 0
    if args.command == "uninstall":
        serial = adb_module.select_device(toolchain, args.serial).serial
        apps.uninstall_package(toolchain, serial, args.package, args.keep_data)
        return 0
    if args.command == "apps":
        serial = adb_module.select_device(toolchain, args.serial).serial
        for package in apps.list_apps(toolchain, serial, third_party=not args.all):
            print(package)
        return 0
    if args.command == "shell":
        serial = adb_module.select_device(toolchain, args.serial).serial
        shell_args = list(args.args)
        if shell_args and shell_args[0] == "--":
            shell_args.pop(0)
        if not shell_args:
            raise AndroidSimError("Provide a shell command after '--', for example: android-sim shell -- getprop")
        result = adb_module.adb(toolchain, serial, ["shell", *shell_args], capture=False)
        return result.returncode
    if args.command == "network":
        serial = adb_module.select_device(toolchain, args.serial).serial
        if args.network_command == "status":
            for key, value in network.status(toolchain, serial).items():
                print(f"{key}: {value}")
        elif args.network_command == "wifi":
            network.wifi(toolchain, serial, args.state == "on")
        elif args.network_command == "speed":
            network.set_speed(toolchain, serial, args.preset)
        elif args.network_command == "delay":
            network.set_delay(toolchain, serial, args.preset)
        elif args.network_command == "proxy":
            if args.value == "clear":
                network.clear_proxy(toolchain, serial)
            else:
                network.set_proxy(toolchain, serial, args.value)
        return 0

    raise AndroidSimError(f"Unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return command_main(args)
    except AndroidSimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
