from __future__ import annotations

import unittest

from android_simulator.config import image_package, validate_avd_name
from android_simulator.errors import AndroidSimError


class ConfigTests(unittest.TestCase):
    def test_image_package_for_play_profile(self) -> None:
        self.assertEqual(
            image_package(37, "play"),
            "system-images;android-37;google_apis_playstore;arm64-v8a",
        )

    def test_validate_avd_name(self) -> None:
        self.assertEqual(validate_avd_name("pixel.play-01"), "pixel.play-01")
        for invalid in ("", "contains space", "../escape", "x" * 81):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AndroidSimError):
                    validate_avd_name(invalid)

    def test_unknown_profile(self) -> None:
        with self.assertRaises(AndroidSimError):
            image_package(37, "unknown")


if __name__ == "__main__":
    unittest.main()
