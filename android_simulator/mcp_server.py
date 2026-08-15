from __future__ import annotations

import json
import sys
from typing import Any

from .computer_use import DeviceController
from .errors import AndroidSimError


TOOLS = [
    {
        "name": "android_observe",
        "description": "Read the current Android UI as a compact semantic tree. Prefer this before vision.",
        "inputSchema": {
            "type": "object",
            "properties": {"full": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    },
    {
        "name": "android_act",
        "description": "Execute one Android computer-use action (tap/type/key/back/home/swipe/scroll/launch/wait).",
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {"action": {"type": "object"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "android_macro",
        "description": "Execute a bounded batch of deterministic Android actions to reduce agent round trips.",
        "inputSchema": {
            "type": "object",
            "required": ["actions"],
            "properties": {
                "actions": {"type": "array", "items": {"type": "object"}, "maxItems": 12}
            },
            "additionalProperties": False,
        },
    },
]


def _ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_content(value: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, separators=(",", ":"))}],
        "isError": False,
    }


def _handle(controller: DeviceController, request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        requested = params.get("protocolVersion") or "2025-06-18"
        return _ok(request_id, {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "jadenfix-android-computer-use", "version": "0.2.0"},
        })
    if method == "ping":
        return _ok(request_id, {})
    if method == "tools/list":
        return _ok(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "android_observe":
            obs = controller.observe()
            return _ok(request_id, _tool_content(obs.compact(max_nodes=500 if arguments.get("full") else 180)))
        if name == "android_act":
            action = arguments.get("action")
            if not isinstance(action, dict):
                raise AndroidSimError("android_act requires an action object")
            result = controller.act(action, controller.observe())
            return _ok(request_id, _tool_content(result.__dict__))
        if name == "android_macro":
            actions = arguments.get("actions")
            if not isinstance(actions, list):
                raise AndroidSimError("android_macro requires an actions array")
            results = controller.macro(actions)
            return _ok(request_id, _tool_content([result.__dict__ for result in results]))
        return _error(request_id, -32602, f"Unknown tool: {name}")
    return _error(request_id, -32601, f"Method not found: {method}")


def serve(controller: DeviceController) -> int:
    """Minimal MCP stdio provider intentionally kept dependency-free.

    It uses newline-delimited JSON-RPC messages, which makes it easy to front with tempera-mcp
    for admission, policy, receipts, routing, and higher-performance production transports.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = _handle(controller, request)
        except (json.JSONDecodeError, AndroidSimError, TypeError, ValueError) as exc:
            response = _error(None, -32603, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0
