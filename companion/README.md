# Android Agent Bridge

This directory contains the optional on-device fast path for `android-agent`.

It is intentionally a very small Android Accessibility service rather than a second application framework. The service exposes semantic UI state and bounded native actions over a loopback-only JSON-lines socket. The host reaches that socket through `adb forward` and authenticates every request with a random per-device token stored in the app-private data directory.

Build it with:

```bash
bash scripts/build-companion.sh
```

Or install/configure it end-to-end on a running managed emulator with:

```bash
android-agent bridge setup
android-agent bridge status
```

The bridge is optional. `android-agent --transport auto ...` prefers it and falls back to the ADB/UIAutomator controller when the bridge is unavailable. `--transport bridge` makes bridge availability mandatory; `--transport adb` forces the independent fallback path.

The autonomous bridge protocol deliberately does not expose arbitrary shell execution. Human/debug shell access remains a separate `android-sim shell -- ...` surface.
