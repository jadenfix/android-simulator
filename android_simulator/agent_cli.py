from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import adb as adb_module
from .agent import AgentConfig, ComputerUseAgent, PlannerClient
from .benchmark import run_benchmark
from .bridge import (
    bridge_status,
    disable_bridge,
    enable_bridge,
    make_controller,
    setup_bridge,
)
from .computer_use import action_schema
from .config import discover_toolchain
from .errors import AndroidSimError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="android-agent", description="Fast computer-use agent for Android Emulator")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SIM_SERIAL"))
    parser.add_argument("--transport", choices=("auto", "bridge", "adb"), default=os.environ.get("ANDROID_AGENT_TRANSPORT", "auto"))
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
    run.add_argument("--settle-timeout-ms", type=int, default=900)
    run.add_argument("--no-vision", action="store_true")
    run.add_argument("--approve-sensitive", action="store_true")
    run.add_argument("--json", action="store_true")

    bench = sub.add_parser("bench", help="Measure observation, action, and fused act-observe latency")
    bench.add_argument("--iterations", type=int, default=20)
    bench.add_argument("--batch-size", type=int, default=8)

    bridge = sub.add_parser("bridge", help="Manage the native Accessibility bridge")
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    setup = bridge_sub.add_parser("setup", help="Build, install, authenticate, enable, and verify the bridge")
    setup.add_argument("--apk", type=Path, help="Use a prebuilt bridge APK instead of building from source")
    bridge_sub.add_parser("status", help="Show bridge installation, enablement, and reachability")
    bridge_sub.add_parser("enable", help="Enable an already installed bridge")
    bridge_sub.add_parser("disable", help="Disable the bridge accessibility service")

    sub.add_parser("tools", help="Print the computer-use action contract")
    sub.add_parser("mcp", help="Serve Android tools over MCP stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    controller = None
    try:
        toolchain = discover_toolchain(require_all=True)
        serial = adb_module.select_device(toolchain, args.serial).serial

        if args.command == "bridge":
            if args.bridge_command == "setup":
                print(json.dumps(setup_bridge(toolchain, serial, apk=args.apk), indent=2))
            elif args.bridge_command == "status":
                print(json.dumps(bridge_status(toolchain, serial), indent=2))
            elif args.bridge_command == "enable":
                enable_bridge(toolchain, serial)
                print(json.dumps(bridge_status(toolchain, serial), indent=2))
            elif args.bridge_command == "disable":
                disable_bridge(toolchain, serial)
                print(json.dumps(bridge_status(toolchain, serial), indent=2))
            return 0

        controller = make_controller(toolchain, serial, args.transport)

        if args.command == "observe":
            obs = controller.observe()
            payload = obs.compact(max_nodes=500 if args.full else 180)
            payload["transport"] = controller.transport_name
            print(json.dumps(payload, indent=2))
            return 0
        if args.command == "act":
            observation = controller.observe()
            action = json.loads(args.action)
            results, next_observation = controller.act_and_observe([action], observation)
            print(json.dumps({
                "transport": controller.transport_name,
                "result": results[0].__dict__ if results else None,
                "next_observation": next_observation.compact(),
            }, indent=2))
            return 0
        if args.command == "bench":
            print(json.dumps(run_benchmark(controller, iterations=args.iterations, batch_size=args.batch_size), indent=2))
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
                settle_timeout_ms=max(0, min(args.settle_timeout_ms, 5000)),
            )
            result = ComputerUseAgent(controller, PlannerClient(config), config).run(args.task)
            payload = {
                "task": result.task,
                "done": result.done,
                "summary": result.summary,
                "steps": result.steps,
                "actions": result.actions,
                "transport": controller.transport_name,
                "history": result.history,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print(
                    f"done={result.done} steps={result.steps} actions={result.actions} "
                    f"transport={controller.transport_name} summary={result.summary}"
                )
            return 0 if result.done else 1
        raise AndroidSimError(f"Unhandled command: {args.command}")
    except (AndroidSimError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        close = getattr(controller, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(main())
