# Install the fast bridge

With the emulator booted:

```bash
android-agent bridge setup
android-agent bridge status
```

The setup command builds the companion APK from source using the installed Android SDK, installs it, provisions a per-emulator host token, enables the Accessibility service when the emulator permits secure-setting automation, creates an ADB forward, and verifies the bridge protocol.

If Android requires a one-time manual Accessibility confirmation, setup opens the relevant settings screen and reports that requirement explicitly. Re-run setup after enabling **Android Agent Bridge**.

To force a particular control plane:

```bash
android-agent --transport bridge observe
android-agent --transport adb observe
```

The default `--transport auto` prefers the native bridge and falls back to the independent ADB/UIAutomator path.
