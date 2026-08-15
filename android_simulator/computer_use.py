from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import adb as adb_module
from .config import Toolchain
from .errors import AndroidSimError


_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    @property
    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)


@dataclass(frozen=True)
class UINode:
    ref: str
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    package: str
    bounds: Rect
    clickable: bool
    enabled: bool
    focusable: bool
    scrollable: bool
    selected: bool
    checked: bool

    @property
    def label(self) -> str:
        return self.text or self.content_desc or self.resource_id.rsplit("/", 1)[-1]

    def compact(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "ref": self.ref,
            "label": self.label,
            "class": self.class_name.rsplit(".", 1)[-1],
            "bounds": [self.bounds.left, self.bounds.top, self.bounds.right, self.bounds.bottom],
        }
        if self.text and self.text != self.label:
            value["text"] = self.text
        if self.content_desc and self.content_desc != self.label:
            value["desc"] = self.content_desc
        if self.resource_id:
            value["id"] = self.resource_id
        if self.clickable:
            value["clickable"] = True
        if self.scrollable:
            value["scrollable"] = True
        if self.checked:
            value["checked"] = True
        if self.selected:
            value["selected"] = True
        return value


@dataclass(frozen=True)
class Observation:
    serial: str
    package: str
    activity: str
    width: int
    height: int
    nodes: tuple[UINode, ...]
    captured_at: float
    latency_ms: float

    def _ranked(self, max_nodes: int) -> list[UINode]:
        return sorted(
            self.nodes,
            key=lambda n: (
                not (n.clickable or n.scrollable),
                not bool(n.label),
                -n.bounds.area,
                n.ref,
            ),
        )[:max_nodes]

    def _hash_body(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "activity": self.activity,
            "screen": [self.width, self.height],
            "nodes": [node.compact() for node in self._ranked(180)],
        }

    @property
    def state_hash(self) -> str:
        payload = json.dumps(self._hash_body(), sort_keys=True, separators=(",", ":"))
        return hashlib.blake2s(payload.encode(), digest_size=12).hexdigest()

    def compact(self, *, max_nodes: int = 180) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "package": self.package,
            "activity": self.activity,
            "screen": [self.width, self.height],
            "state_hash": self.state_hash,
            "latency_ms": round(self.latency_ms, 1),
            "nodes": [node.compact() for node in self._ranked(max_nodes)],
        }


@dataclass(frozen=True)
class ActionResult:
    action: dict[str, Any]
    ok: bool
    latency_ms: float
    detail: str = ""


class DeviceController:
    """Low-overhead Android computer-use primitives over ADB.

    The hot path is semantic hierarchy -> local selector -> ADB input. Screenshots are
    deliberately out of the hot path and are only produced for vision fallback.
    """

    def __init__(self, toolchain: Toolchain, serial: str):
        self.toolchain = toolchain
        self.serial = serial
        self._last_observation: Observation | None = None

    def _shell(self, args: list[str], *, check: bool = True) -> str:
        return adb_module.shell(self.toolchain, self.serial, args, check=check, quiet=True)

    def _window(self) -> tuple[str, str]:
        raw = self._shell(["dumpsys", "window", "windows"], check=False)
        match = re.search(r"(?:mCurrentFocus|mFocusedApp).*? ([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)", raw)
        if not match:
            return "", ""
        component = match.group(1)
        package, _, activity = component.partition("/")
        return package, activity

    def _screen_size(self) -> tuple[int, int]:
        raw = self._shell(["wm", "size"], check=False)
        match = re.search(r"(\d+)x(\d+)", raw)
        return (int(match.group(1)), int(match.group(2))) if match else (1080, 1920)

    def _hierarchy_xml(self) -> str:
        remote = "/sdcard/.android-sim-window.xml"
        self._shell(["uiautomator", "dump", "--compressed", remote], check=False)
        xml = self._shell(["cat", remote], check=False)
        if "<hierarchy" not in xml:
            self._shell(["uiautomator", "dump", remote], check=False)
            xml = self._shell(["cat", remote], check=False)
        if "<hierarchy" not in xml:
            raise AndroidSimError("Could not read Android UI hierarchy")
        return xml[xml.find("<hierarchy") :]

    @staticmethod
    def _parse_nodes(xml: str) -> tuple[UINode, ...]:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise AndroidSimError(f"Invalid UI hierarchy XML: {exc}") from exc
        nodes: list[UINode] = []
        for index, element in enumerate(root.iter("node")):
            attrs = element.attrib
            match = _BOUNDS.fullmatch(attrs.get("bounds", ""))
            if not match:
                continue
            left, top, right, bottom = (int(v) for v in match.groups())
            if right <= left or bottom <= top:
                continue
            nodes.append(UINode(
                ref=f"n{index}",
                text=attrs.get("text", "").strip(),
                content_desc=attrs.get("content-desc", "").strip(),
                resource_id=attrs.get("resource-id", "").strip(),
                class_name=attrs.get("class", "").strip(),
                package=attrs.get("package", "").strip(),
                bounds=Rect(left, top, right, bottom),
                clickable=attrs.get("clickable") == "true",
                enabled=attrs.get("enabled", "true") == "true",
                focusable=attrs.get("focusable") == "true",
                scrollable=attrs.get("scrollable") == "true",
                selected=attrs.get("selected") == "true",
                checked=attrs.get("checked") == "true",
            ))
        return tuple(nodes)

    def observe(self) -> Observation:
        started = time.perf_counter()
        xml = self._hierarchy_xml()
        package, activity = self._window()
        width, height = self._screen_size()
        observation = Observation(
            serial=self.serial,
            package=package,
            activity=activity,
            width=width,
            height=height,
            nodes=self._parse_nodes(xml),
            captured_at=time.time(),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        self._last_observation = observation
        return observation

    def screenshot(self, destination: Path | None = None) -> Path:
        if destination is None:
            fd, name = tempfile.mkstemp(prefix="android-agent-", suffix=".png")
            os.close(fd)
            destination = Path(name)
        remote = "/sdcard/.android-sim-screen.png"
        self._shell(["screencap", "-p", remote])
        adb_module.adb(self.toolchain, self.serial, ["pull", remote, destination], quiet=True)
        return destination

    def find(self, selector: str, observation: Observation | None = None) -> UINode:
        obs = observation or self._last_observation or self.observe()
        if selector.startswith("n") and selector[1:].isdigit():
            for node in obs.nodes:
                if node.ref == selector:
                    return node
        needle = selector.casefold()
        candidates = [node for node in obs.nodes if (
            needle in node.text.casefold()
            or needle in node.content_desc.casefold()
            or needle in node.resource_id.casefold()
        )]
        if not candidates:
            raise AndroidSimError(f"No UI node matches {selector!r}")
        candidates.sort(key=lambda n: (not n.clickable, not n.enabled, n.bounds.area))
        return candidates[0]

    @staticmethod
    def _input_text(value: str) -> str:
        return value.replace("%", "%25").replace(" ", "%s")

    def act(self, action: dict[str, Any], observation: Observation | None = None) -> ActionResult:
        started = time.perf_counter()
        kind = str(action.get("type", ""))
        detail = ""
        obs = observation or self._last_observation
        try:
            if kind == "tap":
                if "ref" in action or "selector" in action:
                    node = self.find(str(action.get("ref") or action.get("selector")), obs)
                    x, y = node.bounds.center
                    detail = node.label
                else:
                    x, y = int(action["x"]), int(action["y"])
                self._shell(["input", "tap", str(x), str(y)])
            elif kind == "long_press":
                node = self.find(str(action.get("ref") or action.get("selector")), obs)
                x, y = node.bounds.center
                duration = int(action.get("duration_ms", 700))
                self._shell(["input", "swipe", str(x), str(y), str(x), str(y), str(duration)])
            elif kind == "type":
                value = str(action.get("text", ""))
                if action.get("clear"):
                    self._shell(["input", "keyevent", "KEYCODE_MOVE_END"], check=False)
                    for _ in range(min(int(action.get("clear_chars", 120)), 300)):
                        self._shell(["input", "keyevent", "KEYCODE_DEL"], check=False)
                self._shell(["input", "text", self._input_text(value)])
                detail = f"{len(value)} chars"
            elif kind == "key":
                self._shell(["input", "keyevent", str(action["key"])])
            elif kind == "back":
                self._shell(["input", "keyevent", "KEYCODE_BACK"])
            elif kind == "home":
                self._shell(["input", "keyevent", "KEYCODE_HOME"])
            elif kind == "enter":
                self._shell(["input", "keyevent", "KEYCODE_ENTER"])
            elif kind == "swipe":
                self._shell(["input", "swipe", str(int(action["x1"])), str(int(action["y1"])), str(int(action["x2"])), str(int(action["y2"])), str(int(action.get("duration_ms", 220)))])
            elif kind == "scroll":
                width, height = (obs.width, obs.height) if obs else self._screen_size()
                direction = str(action.get("direction", "down"))
                amount = max(0.1, min(float(action.get("amount", 0.62)), 0.8))
                x = width // 2
                hi, lo = int(height * 0.78), int(height * max(0.12, 0.78 - amount))
                y1, y2 = (hi, lo) if direction == "down" else (lo, hi)
                self._shell(["input", "swipe", str(x), str(y1), str(x), str(y2), "180"])
            elif kind == "launch":
                package = str(action["package"])
                self._shell(["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
            elif kind == "wait":
                time.sleep(max(0.0, min(float(action.get("seconds", 0.5)), 10.0)))
            else:
                raise AndroidSimError(f"Unsupported computer-use action: {kind!r}")
        except (KeyError, TypeError, ValueError) as exc:
            raise AndroidSimError(f"Malformed {kind!r} action: {action}") from exc
        self._last_observation = None
        return ActionResult(action=action, ok=True, latency_ms=(time.perf_counter() - started) * 1000, detail=detail)

    def macro(self, actions: Iterable[dict[str, Any]], *, max_actions: int = 12) -> list[ActionResult]:
        results: list[ActionResult] = []
        obs = self._last_observation
        for index, action in enumerate(actions):
            if index >= max_actions:
                raise AndroidSimError(f"Macro exceeds {max_actions} action limit")
            results.append(self.act(action, obs))
            obs = None
        return results


def action_schema() -> dict[str, Any]:
    return {
        "types": ["tap", "long_press", "type", "key", "back", "home", "enter", "swipe", "scroll", "launch", "wait"],
        "selector": "Prefer ref from observation. text/resource-id/content-description selectors are also accepted.",
        "batching": "Return multiple safe deterministic actions in one plan when intermediate observation is unnecessary.",
    }
