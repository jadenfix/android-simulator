from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from android_simulator.config import Toolchain
from android_simulator.errors import AndroidSimError
from android_simulator.sdk import resolve_image


class SdkTests(unittest.TestCase):
    def setUp(self) -> None:
        fake = Path("/tmp/fake")
        self.toolchain = Toolchain(fake, fake, fake, fake, fake)

    def test_resolve_uses_newest_candidate(self) -> None:
        packages = {
            "system-images;android-36;google_apis_playstore;arm64-v8a",
            "system-images;android-35;google_apis_playstore;arm64-v8a",
        }
        with patch("android_simulator.sdk.list_packages", return_value=packages):
            selected = resolve_image(
                self.toolchain,
                profile="play",
                requested_api=None,
                arch="arm64-v8a",
            )
        self.assertEqual(selected.api, 36)

    def test_resolve_honors_explicit_api(self) -> None:
        packages = {"system-images;android-35;google_apis;arm64-v8a"}
        with patch("android_simulator.sdk.list_packages", return_value=packages):
            selected = resolve_image(
                self.toolchain,
                profile="google",
                requested_api=35,
                arch="arm64-v8a",
            )
        self.assertEqual(selected.package, "system-images;android-35;google_apis;arm64-v8a")

    def test_resolve_fails_without_profile_image(self) -> None:
        with patch("android_simulator.sdk.list_packages", return_value=set()):
            with self.assertRaises(AndroidSimError):
                resolve_image(
                    self.toolchain,
                    profile="play",
                    requested_api=37,
                    arch="arm64-v8a",
                )


if __name__ == "__main__":
    unittest.main()
