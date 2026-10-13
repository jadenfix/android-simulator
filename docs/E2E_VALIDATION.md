# Real emulator validation

The `actual-emulator-e2e` workflow installs the official Android Emulator and an Android 35 Google APIs x86_64 image on a GitHub Linux KVM runner. It then uses **this repository's CLI** to create an AVD, boot it, read actual Android identity/network/boot properties, inspect packages, capture a screenshot, stop the device and delete the disposable CI AVD. Evidence and emulator logs are uploaded even on failure.

Host-side unit tests alone do not prove Android boots. The workflow must complete successfully at the exact recorded commit before the Linux emulator lane is marked ready. This test does not validate Apple Silicon Hypervisor.framework, Google Play certification, custom Wi-Fi SSIDs or physical device behavior. The original Apple Silicon path needs a separate run on supported hardware.

The repository was reversibly unarchived to permit this requested validation work; its successor link remains intact. No successor repository is modified.
