from __future__ import annotations

import unittest

from android_simulator.cli import build_parser


class CliTests(unittest.TestCase):
    def test_create_parser(self) -> None:
        args = build_parser().parse_args(["create", "--profile", "play", "--api", "37"])
        self.assertEqual(args.command, "create")
        self.assertEqual(args.profile, "play")
        self.assertEqual(args.api, 37)

    def test_network_parser(self) -> None:
        args = build_parser().parse_args(["network", "wifi", "on"])
        self.assertEqual(args.network_command, "wifi")
        self.assertEqual(args.state, "on")


if __name__ == "__main__":
    unittest.main()
