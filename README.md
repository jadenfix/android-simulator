# Android Simulator for Apple Silicon

> **Archived — development moved to [tempera-dev/tempera-android](https://github.com/tempera-dev/tempera-android).**
>
> The successor is a cross-platform Rust Android agent engine with a persistent
> daemon, revision-safe native Accessibility bridge, independent ADB fallback,
> optional Appium support, sessions, MCP, dashboard, skills, and evals. Install
> the public alpha from the [v0.4.0-alpha.1 release](https://github.com/tempera-dev/tempera-android/releases/tag/v0.4.0-alpha.1).
> This repository remains available as the historical source and complete import
> lineage; it will receive no further feature development.

A reproducible, command-line-managed Android environment for an M-series Mac.
It uses the **official Android Emulator** as the virtualization engine and adds
the code needed to install the SDK, create isolated phone-like devices, start
custom simulated Wi-Fi, install or download apps, inspect identity, and control
network behavior.

The default `play` profile uses an ARM64 Google Play system image. That gives you
Google Play Services and the official Play Store while preserving the locked,
production-like behavior of a normal certified Android device.

## Why this approach

Building Android's emulator, QEMU integration, system images, Google Play
Services, and a Play-certified image from scratch would be slower, less secure,
and less phone-like than the maintained upstream implementation. This repo
builds the orchestration and reproducibility layer from scratch while reusing
the official execution engine.

## What works

- Native Apple Silicon / `arm64-v8a` system images; no Rosetta requirement.
- Isolated Android Virtual Devices with persistent apps and state.
- Google Play Store profile, Google APIs profile, or root-oriented AOSP profile.
- Simulated Wi-Fi with a custom SSID and optional WPA2 password on Emulator
  36.5 or newer.
- Internet access through the Mac's active network, custom DNS, proxies, and
  latency/speed presets.
- APK installation, split-APK installation, HTTPS APK downloads with optional
  SHA-256 verification, and arbitrary downloads into Android's Downloads app.
- Fresh per-AVD state, factory reset, and separate identity creation.
- GPS, camera, audio, sensors, clipboard, screenshots, and the normal Emulator
  UI supplied by the official engine.

## Honest boundaries

This is a real Android OS image running in a hardware-accelerated virtual device,
but it is not physical phone hardware.

- The Wi-Fi radio is simulated. Internet traffic exits through the Mac's
  network; the AVD does not join the physical LAN as an independent radio.
- Android 8+ scopes `ANDROID_ID` to app-signing key, Android user, and device.
  The shell-visible value printed by `android-sim identity` is diagnostic and is
  not necessarily the value every app sees.
- A fresh AVD has separate state and a fresh framework identity. The project
  does not forge IMEI values, build fingerprints, hardware attestation, or Play
  Integrity results.
- Banking, DRM, anti-cheat, and hardware-bound apps may reject all emulators.
- The official Play profile is intentionally non-root. Use `aosp` for system
  debugging; it does not include Google Play.

See [Architecture](docs/ARCHITECTURE.md) for the full model.

## Requirements

- Apple Silicon Mac (`M1`, `M2`, `M3`, `M4`, or newer)
- Modern macOS
- At least 8 GB RAM; 16 GB is much more comfortable
- At least 20 GB free disk space; 30+ GB is recommended
- Homebrew, or permission for the bootstrap to install it

## One-command setup

```bash
git clone git@github.com:Jadenfix/android-simulator.git
cd android-simulator
./scripts/bootstrap-macos.sh
```

The script installs:

- Temurin JDK 21
- Android SDK command-line tools
- Android Emulator and platform tools
- the local `android-sim` CLI
- the newest compatible Google Play ARM64 image among API 37, 36, and 35
- an isolated AVD named `android-sim-play`

It also adds a clearly marked Android SDK block to `~/.zshrc`.

Install Android Studio too:

```bash
./scripts/bootstrap-macos.sh --with-studio
```

Allow the script to install Homebrew when it is absent:

```bash
./scripts/bootstrap-macos.sh --install-homebrew
```

Install tools without downloading a multi-gigabyte system image yet:

```bash
./scripts/bootstrap-macos.sh --no-create
```

## Start Android with simulated Wi-Fi

```bash
android-sim start android-sim-play \
  --wifi-ssid "JadenAndroid" \
  --wifi-password "replace-this-password"
```

The first boot takes longer. Later boots use Android Emulator quick-boot
snapshots unless `--cold` is supplied.

Useful variants:

```bash
# Cold boot, explicit DNS
android-sim start android-sim-play --cold --dns 1.1.1.1,8.8.8.8

# Headless automation
android-sim start android-sim-play --headless --no-audio

# See configured devices and active ADB endpoints
android-sim list

# Stop the only running emulator
android-sim stop
```

## Install and download apps

### Official Google Play Store

Start the `play` profile, sign into Google Play once in the emulator, then open
an app listing by package name:

```bash
android-sim play com.spotify.music
android-sim play com.google.android.youtube
```

Installation remains inside the official Play Store UI. The project does not
automate Google credentials or scrape APKs from the store.

### Local APK

```bash
android-sim install ~/Downloads/app.apk
```

For split APKs, put all device-compatible `.apk` files in one directory:

```bash
android-sim install ~/Downloads/my-app-splits/
```

The CLI uses `adb install-multiple` when more than one APK is present.

### Trusted direct APK URL

```bash
android-sim install-url \
  https://publisher.example/releases/app-arm64.apk \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

HTTPS is mandatory by default. `--allow-http` exists only for controlled local
networks and should not be used for public downloads.

### Put a file in Android Downloads

```bash
android-sim download https://example.com/document.pdf
```

The resulting file appears under `/sdcard/Download`.

### App lifecycle

```bash
android-sim apps                 # third-party packages
android-sim apps --all           # include system packages
android-sim launch com.example.app
android-sim uninstall com.example.app
```

## Device identity

Inspect the running environment:

```bash
android-sim identity
android-sim identity --json
```

Create a separate, fresh AVD based on the same managed profile:

```bash
android-sim new-identity android-sim-play
```

This produces a new AVD name with a random suffix and a separate data partition.
It is preferable to spoofing protected identifiers because it follows Android's
normal device lifecycle.

Factory-reset the original AVD:

```bash
android-sim factory-reset android-sim-play --yes
```

This is destructive: apps, accounts, files, settings, and snapshots are erased.

## Profiles

```bash
# Closest to an ordinary consumer Android phone; Play Store; no root
android-sim create --name phone-play --profile play

# Google APIs / Play Services, but no Play Store app
android-sim create --name phone-google --profile google

# AOSP image for lower-level debugging; no Google apps
android-sim create --name phone-aosp --profile aosp
```

Pin an API level or tune resources:

```bash
android-sim create \
  --name phone-api36 \
  --profile play \
  --api 36 \
  --ram-mb 4096 \
  --data-gb 24
```

The automatic RAM choice is 3 GB on smaller Macs, 4 GB on 16 GB Macs, and 6 GB
on hosts with at least 32 GB.

## Network controls

```bash
android-sim network status
android-sim network wifi off
android-sim network wifi on

# Emulator console presets
android-sim network speed lte
android-sim network delay edge

# Global Android HTTP proxy
android-sim network proxy 10.0.2.2:8080
android-sim network proxy clear
```

To reach a web server running on the Mac's loopback interface from Android, use
`10.0.2.2` instead of `127.0.0.1`:

```text
Mac:     http://127.0.0.1:8000
Android: http://10.0.2.2:8000
```

## Raw ADB shell access

```bash
android-sim shell -- getprop ro.build.version.release
android-sim shell -- pm list packages -3
```

When multiple emulators are active, add `--serial emulator-5554` to commands
that target a running device.

## Development

The CLI is standard-library Python and has no runtime package dependencies. The local installer uses a virtual environment and a `.pth` link, so it does not need PyPI.

```bash
make test
make lint
make smoke   # boots the default AVD; macOS only
python3 -m android_simulator --help
```

CI runs syntax and unit tests on macOS and Linux, plus ShellCheck for bootstrap
scripts. Actual AVD boot testing remains a local macOS integration test because
hosted CI virtualization and image availability vary.

## Troubleshooting

Run the environment diagnosis first:

```bash
android-sim doctor
```

Then see [Troubleshooting](docs/TROUBLESHOOTING.md).

## Upstream references

- [Install Android Studio](https://developer.android.com/studio/install)
- [Android command-line tools](https://developer.android.com/studio)
- [`sdkmanager`](https://developer.android.com/tools/sdkmanager)
- [`avdmanager`](https://developer.android.com/tools/avdmanager)
- [Start the emulator from the command line](https://developer.android.com/studio/run/emulator-commandline)
- [Emulator network address space](https://developer.android.com/studio/run/emulator-networking-address)
- [Advanced emulator networking](https://developer.android.com/studio/run/emulator-networking-advanced)
- [`adb`](https://developer.android.com/tools/adb)
- [`Settings.Secure.ANDROID_ID`](https://developer.android.com/reference/android/provider/Settings.Secure#ANDROID_ID)
