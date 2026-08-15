from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_API_CANDIDATES, Toolchain, image_package
from .errors import AndroidSimError
from .util import run


@dataclass(frozen=True)
class ImageSelection:
    api: int
    profile: str
    arch: str
    package: str


def sdk_env(toolchain: Toolchain) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["ANDROID_SDK_ROOT"] = str(toolchain.sdk_root)
    env["ANDROID_HOME"] = str(toolchain.sdk_root)
    return env


def list_packages(toolchain: Toolchain) -> set[str]:
    result = run(
        [toolchain.sdkmanager, f"--sdk_root={toolchain.sdk_root}", "--list"],
        env=sdk_env(toolchain),
    )
    packages: set[str] = set()
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("Path", "Installed", "Available", "=")):
            continue
        package = line.split("|", 1)[0].strip()
        if ";" in package or package in {"emulator", "platform-tools"}:
            packages.add(package)
    return packages


def resolve_image(
    toolchain: Toolchain,
    *,
    profile: str,
    requested_api: int | None,
    arch: str,
) -> ImageSelection:
    available = list_packages(toolchain)
    candidates = (requested_api,) if requested_api else DEFAULT_API_CANDIDATES
    for api in candidates:
        assert api is not None
        package = image_package(api, profile, arch)
        if package in available:
            return ImageSelection(api=api, profile=profile, arch=arch, package=package)
    requested = f"API {requested_api}" if requested_api else f"APIs {', '.join(map(str, candidates))}"
    raise AndroidSimError(
        f"No {profile!r} {arch} system image found for {requested}. "
        "Run 'android-sim images' to inspect what sdkmanager exposes, or pass --api explicitly."
    )


def install_base_packages(toolchain: Toolchain) -> None:
    run(
        [
            toolchain.sdkmanager,
            f"--sdk_root={toolchain.sdk_root}",
            "platform-tools",
            "emulator",
            "cmdline-tools;latest",
        ],
        capture=False,
        env=sdk_env(toolchain),
    )


def install_image(toolchain: Toolchain, selection: ImageSelection) -> None:
    run(
        [
            toolchain.sdkmanager,
            f"--sdk_root={toolchain.sdk_root}",
            f"platforms;android-{selection.api}",
            selection.package,
        ],
        capture=False,
        env=sdk_env(toolchain),
    )
