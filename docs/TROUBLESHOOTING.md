# Troubleshooting

## `sdkmanager` cannot find Java

Run:

```bash
brew install --cask temurin@21
export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
```

Then rerun `./scripts/bootstrap-macos.sh`.

## No Play Store image appears for API 37

List what the current SDK repository exposes:

```bash
android-sim images
```

Then create a supported stable fallback explicitly:

```bash
android-sim create --name android-sim-play --profile play --api 36
```

The CLI already tries API 37, then 36, then 35 when `--api` is omitted.

## The emulator boots but the internet does not work

```bash
android-sim network status
android-sim network wifi on
```

Try explicit DNS on a cold boot:

```bash
android-sim stop
android-sim start android-sim-play --cold --dns 1.1.1.1,8.8.8.8
```

A corporate firewall, VPN, proxy, or DNS filter on the Mac can also affect the
emulator because outbound traffic uses the host network.

## Access a server running on the Mac

Inside Android, `127.0.0.1` means the emulator itself. Use `10.0.2.2` to reach a
service bound to the Mac's loopback interface. For example, Android can reach a
Mac server on port 8000 at `http://10.0.2.2:8000`.

## An APK fails with `INSTALL_FAILED_NO_MATCHING_ABIS`

The M2 environment runs an ARM64 (`arm64-v8a`) Android image. Install an APK that
contains ARM64 native libraries. An x86-only APK is not compatible.

## A banking, DRM, or game app refuses to run

The Play profile is production-signed and includes Play Services, but it remains
an emulator and does not become physical hardware. Apps may require hardware
attestation, Widevine levels, telephony, NFC secure elements, or vendor-specific
components unavailable in an AVD. This project does not bypass those checks.

## Resetting identity removed all apps

That is expected. A factory reset replaces the writable user-data state. Use a
separate identity instead when preserving the original environment matters:

```bash
android-sim new-identity android-sim-play
android-sim list
```
