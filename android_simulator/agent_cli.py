from __future__ import annotations

import argparse
import json
import os
import sys

from . import adb as adb_module
from .agent import AgentConfig, ComputerUseAgent, PlannerClient
from .computer_use import DeviceController, action_schema
from .config import discover_toolchain
from .errors import AndroidSimError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="android-agent", description="Fast computer-use agent for Android Emulator")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SIM_SERIAL"))
    parser.add_argument("--model", default=os.environ.get("ANDROID_AGENT_MODEL", ""))
    parser.add_argument("--endpoint", default=os.environ.get("ANDROID_AGENT_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions"))
    parser.add_argument("--api-key", default=os.environ.get("ANDROID_AGENT_API_KEY", ""))
    sub = parser.add_subparsers(dest="command", required=True)

    observe = sub.add_parser("observe", help="Print a compact semantic observation")
    observe.add_argument("--full", action="store_true", help="Include more UI nodes")

    act = sub.add_parser("act", help="Execute one JSON action")
    act.add_argument("action", help='JSON, e.g. {"type":"tap","selector":"Settings"}')

    run = sub.add_parser("run", help="Run an autonomous task")
    run.add_argument("task")
    run.add_argument("--max-steps", type=int, default=40)
    run.add_argument("--max-actions-per-step", type=int, default=8)
    run.add_argument("--no-vision", action="store_true")
    run.add_argument("--approve-sensitive", action="store_true")
    run.add_argument("--json", action="store_true")

    sub.add_parser("tools", help="Print the computer-use action contract")
    sub.add_parser("mcp", help="Serve Android tools over MCP stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        toolchain = discover_toolchain(require_all=True)
        serial = adb_module.select_device(toolchain, args.serial).serial
        controller = DeviceController(toolchain, serial)

        if args.command == "observe":
            obs = controller.observe()
            print(json.dumps(obs.compact(max_nodes=500 if args.full else 180), indent=2))
            return 0
        if args.command == "act":
            action = json.loads(args.action)
            result = controller.act(action, controller.observe())
            print(json.dumps(result.__dict__, indent=2))
            return 0
        if args.command == "tools":
            print(json.dumps(action_schema(), indent=2))
            return 0
        if args.command == "mcp":
            from .mcp_server import serve
            return serve(controller)
        if args.command == "run":
            config = AgentConfig(
                endpoint=args.endpoint,
                model=args.model,
                api_key=args.api_key,
                max_steps=args.max_steps,
                max_actions_per_step=args.max_actions_per_step,
                use_vision=not args.no_vision,
                auto_approve_sensitive=args.approve_sensitive,
            )
            result = ComputerUseAgent(controller, PlannerClient(config), config).run(args.task)
            payload = {
                "task": result.task,
                "done": result.done,
                "summary": result.summary,
                "steps": result.steps,
                "actions": result.actions,
                "history": result.history,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"done={result.done} steps={result.steps} actions={result.actions} summary={result.summary}")
            return 0 if result.done else 1
        raise AndroidSimError(f"Unhandled command: {args.command}")
    except (AndroidSimError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
