from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from android_simulator.adb import emulator_avd_name
from android_simulator.config import Toolchain
from android_simulator.util import Result


TOOLCHAIN = Toolchain(
    sdk_root=Path('/sdk'),
    sdkmanager=Path('/sdk/sdkmanager'),
    avdmanager=Path('/sdk/avdmanager'),
    adb=Path('/sdk/adb'),
    emulator=Path('/sdk/emulator'),
)


class AdbTests(unittest.TestCase):
    @patch('android_simulator.adb.shell', return_value='phone-play')
    def test_avd_name_prefers_boot_property(self, shell_mock) -> None:
        with patch('android_simulator.adb.adb') as adb_mock:
            self.assertEqual(emulator_avd_name(TOOLCHAIN, 'emulator-5554'), 'phone-play')
            adb_mock.assert_not_called()
        shell_mock.assert_called_once()

    @patch('android_simulator.adb.shell', return_value='')
    @patch(
        'android_simulator.adb.adb',
        return_value=Result(
            args=('adb',),
            returncode=0,
            stdout='phone-fallback\nOK\n',
            stderr='',
        ),
    )
    def test_avd_name_falls_back_to_console(self, _adb_mock, _shell_mock) -> None:
        self.assertEqual(emulator_avd_name(TOOLCHAIN, 'emulator-5554'), 'phone-fallback')


if __name__ == '__main__':
    unittest.main()
