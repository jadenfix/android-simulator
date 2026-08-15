from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from android_simulator.errors import AndroidSimError
from android_simulator.util import download, parse_version, safe_download_name, validate_sha256


class UtilTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("Android emulator version 36.5.12.0"), (36, 5, 12, 0))
        self.assertEqual(parse_version("unknown"), ())

    def test_safe_download_name(self) -> None:
        self.assertEqual(safe_download_name("https://example.com/files/My%20App.apk"), "My_App.apk")
        self.assertEqual(safe_download_name("https://example.com/"), "download.bin")

    def test_sha_validation(self) -> None:
        digest = "a" * 64
        self.assertEqual(validate_sha256(digest.upper()), digest)
        with self.assertRaises(AndroidSimError):
            validate_sha256("abc")

    def test_download_rejects_plain_http_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(AndroidSimError):
                download("http://example.com/app.apk", Path(temp_dir) / "app.apk")


if __name__ == "__main__":
    unittest.main()
