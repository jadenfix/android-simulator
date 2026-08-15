from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from android_simulator.avd import _wifi_netsim_args, configure_avd
from android_simulator.errors import AndroidSimError


class AvdTests(unittest.TestCase):
    def test_wifi_args_quote_spaces(self) -> None:
        value = _wifi_netsim_args("Jaden WiFi", "password123")
        self.assertIn("--wifi", value)
        self.assertIn("Jaden WiFi", value)
        self.assertIn("password123", value)

    def test_wifi_password_minimum(self) -> None:
        with self.assertRaises(AndroidSimError):
            _wifi_netsim_args("ssid", "short")

    def test_configure_avd_preserves_and_updates_ini(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "demo.avd" / "config.ini"
            config.parent.mkdir(parents=True)
            config.write_text("existing.key=keep\nhw.ramSize=1024\n", encoding="utf-8")
            with patch("android_simulator.avd.avd_home", return_value=root):
                configure_avd("demo", ram_mb=4096, data_gb=16, play_store=True)
            text = config.read_text(encoding="utf-8")
            self.assertIn("existing.key=keep", text)
            self.assertIn("hw.ramSize=4096", text)
            self.assertIn("disk.dataPartition.size=16G", text)
            self.assertIn("PlayStore.enabled=true", text)


if __name__ == "__main__":
    unittest.main()
