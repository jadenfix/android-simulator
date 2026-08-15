# Architecture

## Decision: reuse the official emulator engine

This repository deliberately does **not** reimplement Android, QEMU, hardware
virtualization, Google Play Services, or the Play Store. The official Android
Emulator already provides the Apple Silicon virtualization path, maintained
system images, snapshots, ADB integration, graphics, sensors, and networking.
Rebuilding that stack would increase risk and produce a less phone-like result.

The project instead builds the reproducible layer that Android Studio does not
provide as a portable, reviewable environment:

1. `scripts/bootstrap-macos.sh` installs a pinned class of prerequisites through
   Homebrew and installs first-party SDK packages into `~/Library/Android/sdk`.
2. `android_simulator.sdk` resolves a compatible ARM64 system image and installs
   it through `sdkmanager`.
3. `android_simulator.avd` creates and records isolated AVDs, configures sane
   Apple Silicon resource limits, chooses a free console port, and waits for a
   complete Android boot.
4. `android_simulator.adb`, `apps`, and `network` expose safe device, app, and
   network operations.
5. Host-side metadata under `~/.android-simulator/instances` records the profile
   and a UUID without pretending that UUID is an Android framework identifier.

## Profiles

| Profile | Image tag | Google Play | Google APIs | Root expectation | Intended use |
|---|---|---:|---:|---:|---|
| `play` | `google_apis_playstore` | Yes | Yes | No | Consumer-like app use and Play installs |
| `google` | `google_apis` | No store | Yes | Not promised | Google API development without the store |
| `aosp` | `default` | No | No | AOSP emulator images can support `adb root` | System/debug work |

`play` is the default because it is closest to a normal certified Android phone.
It intentionally remains locked like a production device.

## Identity model

Every AVD has a separate writable data partition. A newly created AVD or a
factory reset receives fresh Android user state. The host-side `instance_uuid`
is for orchestration only.

Modern `ANDROID_ID` is not one global hardware number. Android scopes it to the
combination of app-signing key, Android user, and device. Therefore:

- `android-sim identity` reports the value visible to the ADB shell as a
  diagnostic, not a promise that every app sees that same value.
- `android-sim new-identity` creates a genuinely separate AVD instead of
  patching protected settings.
- `android-sim factory-reset --yes` wipes the AVD and its apps/accounts.
- The project does not spoof IMEI, build fingerprints, hardware attestation, or
  Play Integrity results.

## Network model

The emulator connects outbound through its virtual router and the Mac's current
network. Recent emulator versions can expose a simulated Wi-Fi access point with
an explicit SSID and WPA2 password. This is still virtual radio behavior; it
cannot turn the emulator into a physical participant on the Mac's Wi-Fi LAN.

The CLI also exposes Wi-Fi toggling, latency/speed presets, proxy settings, DNS
selection at startup, and the emulator's standard `10.0.2.2` host alias.
