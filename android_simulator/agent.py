from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .computer_use import DeviceController, Observation, action_schema
from .errors import AndroidSimError


SENSITIVE_LABELS = {
    "send", "post", "publish", "buy", "purchase", "pay", "transfer", "confirm purchase",
    "delete", "remove account", "factory reset", "subscribe", "book", "order", "submit",
}


@dataclass
class AgentConfig:
    endpoint: str = field(default_factory=lambda: os.environ.get("ANDROID_AGENT_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions"))
    model: str = field(default_factory=lambda: os.environ.get("ANDROID_AGENT_MODEL", ""))
    api_key: str = field(default_factory=lambda: os.environ.get("ANDROID_AGENT_API_KEY", ""))
    timeout_seconds: float = 45.0
    max_steps: int = 40
    max_actions_per_step: int = 8
    use_vision: bool = True
    auto_approve_sensitive: bool = False


@dataclass
class AgentRun:
    task: str
    done: bool
    summary: str
    steps: int
    actions: int
    history: list[dict[str, Any]]


class PlannerClient:
    """Dependency-free client for OpenAI-compatible chat endpoints."""

    def __init__(self, config: AgentConfig):
        self.config = config
        if not config.model:
            raise AndroidSimError("Set ANDROID_AGENT_MODEL or pass --model")

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise AndroidSimError(f"Planner did not return JSON: {text[:300]}")
            value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise AndroidSimError("Planner response must be a JSON object")
        return value

    def _post(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(self.config.endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AndroidSimError(f"Planner request failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AndroidSimError(f"Unexpected planner response: {body}") from exc
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return self._extract_json(str(content))

    def plan(
        self,
        task: str,
        observation: Observation,
        history: list[dict[str, Any]],
        *,
        screenshot: Path | None = None,
    ) -> dict[str, Any]:
        system = (
            "You control an Android phone. Produce ONLY JSON. Prefer semantic refs from the UI tree over coordinates. "
            "Batch deterministic actions to reduce latency, but never include a second ref/selector action after a prior "
            "ref/selector action in the same batch because semantic refs are scoped to one UI state. It is okay to batch "
            "non-selector follow-ups such as type, enter, wait, key, or coordinate gestures. Never invent a ref. If the "
            "hierarchy is insufficient and an image would help, set need_vision=true and actions=[]. If the task is complete, "
            "set done=true. Schema: {done:boolean, summary:string, need_vision:boolean, actions:[action...]}. Action schema: "
            + json.dumps(action_schema(), separators=(",", ":"))
        )
        text = json.dumps({
            "task": task,
            "observation": observation.compact(),
            "recent_history": history[-6:],
        }, separators=(",", ":"))
        if screenshot is None:
            user_content: Any = text
        else:
            image = base64.b64encode(screenshot.read_bytes()).decode()
            user_content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
            ]
        return self._post([
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ])


def _sensitive(action: dict[str, Any], observation: Observation) -> str | None:
    if action.get("type") != "tap":
        return None
    ref = str(action.get("ref") or action.get("selector") or "")
    if not ref:
        return None
    needle = ref.casefold()
    for node in observation.nodes:
        if node.ref == ref or needle in node.label.casefold():
            label = node.label.casefold().strip()
            if any(term in label for term in SENSITIVE_LABELS):
                return node.label or ref
    return None


def _safe_batch(actions: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Trim a planner batch before it can reuse semantic selectors in a new UI state."""
    result: list[dict[str, Any]] = []
    selector_seen = False
    for action in actions[:limit]:
        uses_selector = bool(action.get("ref") or action.get("selector"))
        if uses_selector and selector_seen:
            break
        result.append(action)
        selector_seen = selector_seen or uses_selector
    return result


class ComputerUseAgent:
    def __init__(self, controller: DeviceController, planner: PlannerClient, config: AgentConfig):
        self.controller = controller
        self.planner = planner
        self.config = config

    def run(self, task: str) -> AgentRun:
        history: list[dict[str, Any]] = []
        total_actions = 0
        last_hash = ""
        repeated_states = 0
        for step in range(1, self.config.max_steps + 1):
            observation = self.controller.observe()
            if observation.state_hash == last_hash:
                repeated_states += 1
            else:
                repeated_states = 0
            last_hash = observation.state_hash

            plan = self.planner.plan(task, observation, history)
            if plan.get("need_vision"):
                if not self.config.use_vision:
                    raise AndroidSimError("Planner requested vision but vision fallback is disabled")
                screenshot = self.controller.screenshot()
                try:
                    plan = self.planner.plan(task, observation, history, screenshot=screenshot)
                finally:
                    screenshot.unlink(missing_ok=True)

            if bool(plan.get("done")):
                return AgentRun(task, True, str(plan.get("summary", "done")), step, total_actions, history)

            actions = plan.get("actions")
            if not isinstance(actions, list) or not actions:
                raise AndroidSimError(f"Planner returned no executable actions at step {step}: {plan}")
            if not all(isinstance(action, dict) for action in actions):
                raise AndroidSimError(f"Planner returned an invalid action batch: {actions!r}")
            actions = _safe_batch(actions, self.config.max_actions_per_step)
            if not actions:
                raise AndroidSimError("Planner batch became empty after safety validation")

            for action in actions:
                sensitive = _sensitive(action, observation)
                if sensitive and not self.config.auto_approve_sensitive:
                    raise AndroidSimError(
                        f"Approval required before sensitive UI action {sensitive!r}. "
                        "Re-run with --approve-sensitive if this task is intentionally authorized."
                    )

            # The controller compiles the full safe batch into one device-side shell transaction.
            results = self.controller.macro(actions, max_actions=self.config.max_actions_per_step)
            total_actions += len(results)
            for result in results:
                history.append({
                    "step": step,
                    "state": observation.state_hash,
                    "action": result.action,
                    "ok": result.ok,
                    "latency_ms": round(result.latency_ms, 1),
                    "detail": result.detail,
                })

            if repeated_states >= 4:
                raise AndroidSimError("Agent is stuck: UI state repeated without progress")

        return AgentRun(task, False, f"max steps ({self.config.max_steps}) reached", self.config.max_steps, total_actions, history)
