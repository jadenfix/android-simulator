from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from android_simulator.apps import collect_apks
from android_simulator.errors import AndroidSimError


class AppsTests(unittest.TestCase):
    def test_collect_split_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "base.apk").touch()
            (root / "split_config.arm64_v8a.apk").touch()
            (root / "ignored.txt").touch()
            result = collect_apks([root])
            self.assertEqual([path.name for path in result], ["base.apk", "split_config.arm64_v8a.apk"])

    def test_apks_archive_needs_bundletool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "app.apks"
            archive.touch()
            with self.assertRaises(AndroidSimError):
                collect_apks([archive])


if __name__ == "__main__":
    unittest.main()
