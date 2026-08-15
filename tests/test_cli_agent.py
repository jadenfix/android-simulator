from __future__ import annotations

import unittest

from android_simulator.agent_cli import build_parser


class AgentCliTests(unittest.TestCase):
    def test_bridge_setup_parser(self):
        args = build_parser().parse_args(["--transport", "bridge", "bridge", "setup"])
        self.assertEqual(args.transport, "bridge")
        self.assertEqual(args.command, "bridge")
        self.assertEqual(args.bridge_command, "setup")

    def test_run_progressive_perception_parser(self):
        args = build_parser().parse_args([
            "--model", "fast-model",
            "--vision-model", "vision-model",
            "run", "Open Settings",
            "--task-context-nodes", "48",
            "--full-context-nodes", "320",
        ])
        self.assertEqual(args.model, "fast-model")
        self.assertEqual(args.vision_model, "vision-model")
        self.assertEqual(args.task_context_nodes, 48)
        self.assertEqual(args.full_context_nodes, 320)


if __name__ == "__main__":
    unittest.main()
