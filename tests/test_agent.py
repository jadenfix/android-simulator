from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from android_simulator.agent import AgentConfig, ComputerUseAgent
from android_simulator.computer_use import ActionResult, Observation, Rect, StaleStateError, UINode


def obs(revision: int, label: str = "Settings") -> Observation:
    node = UINode(
        ref="b1",
        text=label,
        content_desc="",
        resource_id="com.demo:id/settings",
        class_name="android.widget.Button",
        package="com.demo",
        bounds=Rect(0, 0, 200, 80),
        clickable=True,
        enabled=True,
        focusable=False,
        scrollable=False,
        selected=False,
        checked=False,
    )
    return Observation("emulator-5554", "com.demo", ".Main", 1080, 1920, (node,), 1.0, 1.0, revision)


class FakePlanner:
    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = []

    def plan(self, task, observation, history, *, context_mode="ranked", screenshot=None, model=None):
        self.calls.append((context_mode, screenshot is not None, model))
        value = dict(self.plans.pop(0))
        value.setdefault("_perception", "vision" if screenshot else context_mode)
        value.setdefault("_planner_model", model or "fake")
        value.setdefault("_planner_latency_ms", 1.0)
        return value


class FakeController:
    transport_name = "fake"

    def __init__(self, observations, *, stale_once=False):
        self.observations = list(observations)
        self.current = self.observations.pop(0)
        self.stale_once = stale_once
        self.actions = []

    def observe(self):
        return self.current

    def screenshot(self):
        handle = NamedTemporaryFile(suffix=".png", delete=False)
        handle.write(b"png")
        handle.close()
        return Path(handle.name)

    def act_and_observe(self, actions, observation, *, timeout_ms=900):
        if self.stale_once:
            self.stale_once = False
            self.current = self.observations.pop(0)
            raise StaleStateError(self.current)
        self.actions.extend(actions)
        if self.observations:
            self.current = self.observations.pop(0)
        return [ActionResult(action, True, 1.0, "ok") for action in actions], self.current


class AgentTests(unittest.TestCase):
    def test_ranked_then_full_context_escalation(self):
        controller = FakeController([obs(1), obs(2)])
        planner = FakePlanner([
            {"done": False, "need_context": True, "need_vision": False, "actions": []},
            {"done": False, "need_context": False, "need_vision": False, "actions": [{"type": "tap", "ref": "b1"}]},
            {"done": True, "summary": "done", "actions": []},
        ])
        config = AgentConfig(model="fake", use_vision=False, max_steps=3)
        result = ComputerUseAgent(controller, planner, config).run("Open Settings")
        self.assertTrue(result.done)
        self.assertEqual(planner.calls[0][0], "ranked")
        self.assertEqual(planner.calls[1][0], "full")
        self.assertEqual(len(controller.actions), 1)

    def test_vision_is_last_perception_tier(self):
        controller = FakeController([obs(1), obs(2)])
        planner = FakePlanner([
            {"done": False, "need_context": False, "need_vision": True, "actions": []},
            {"done": False, "need_context": False, "need_vision": False, "actions": [{"type": "tap", "ref": "b1"}]},
            {"done": True, "summary": "done", "actions": []},
        ])
        config = AgentConfig(model="fast", vision_model="vision", max_steps=3)
        result = ComputerUseAgent(controller, planner, config).run("Open Settings")
        self.assertTrue(result.done)
        self.assertFalse(planner.calls[0][1])
        self.assertTrue(planner.calls[1][1])
        self.assertEqual(planner.calls[1][2], "vision")

    def test_stale_revision_replans_without_executing_old_action(self):
        controller = FakeController([obs(1), obs(2), obs(3)], stale_once=True)
        planner = FakePlanner([
            {"done": False, "actions": [{"type": "tap", "ref": "b1"}]},
            {"done": False, "actions": [{"type": "tap", "ref": "b1"}]},
            {"done": True, "summary": "done", "actions": []},
        ])
        config = AgentConfig(model="fake", max_steps=4)
        result = ComputerUseAgent(controller, planner, config).run("Open Settings")
        self.assertTrue(result.done)
        self.assertEqual(len(controller.actions), 1)
        self.assertTrue(any(item.get("event") == "stale_plan_rejected" for item in result.history))


if __name__ == "__main__":
    unittest.main()
