#!/usr/bin/env python3
"""MCP adapter over expctl (CLI-first)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List


EXPCTL_PATH = Path(__file__).resolve().parent / "expctl.py"


def _run_expctl(args: List[str]) -> Dict[str, Any]:
    cmd = [sys.executable, str(EXPCTL_PATH), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if stdout:
        try:
            data = json.loads(stdout)
        except Exception:
            data = {"raw": stdout}
    else:
        data = {}
    if proc.returncode != 0:
        return {
            "error": {
                "code": "expctl_failed",
                "message": "expctl command failed",
                "exit_code": proc.returncode,
                "stderr": stderr,
                "data": data,
            }
        }
    return {"result": data}


def _tool_list() -> Dict[str, Any]:
    return {
        "tools": [
            {"name": "target_set", "description": "Set or activate target endpoint profile."},
            {"name": "target_get", "description": "Get target endpoint profile."},
            {"name": "experiment_create", "description": "Create experiment from profile."},
            {"name": "experiment_run", "description": "Run experiment (proxy/full/auto)."},
            {"name": "experiment_status", "description": "Get experiment run status."},
            {"name": "experiment_analysis", "description": "Get experiment run analysis."},
            {"name": "experiment_compare", "description": "Compare two experiment runs."},
            {"name": "leaderboard_get", "description": "Get experiment leaderboard."},
            {"name": "qa_batch_run", "description": "Run QA ask-batch."},
            {"name": "eval_run_create", "description": "Create eval run."},
            {"name": "eval_report_get", "description": "Get eval report."},
            {"name": "gold_dataset_export", "description": "Export gold dataset artifact."},
            {"name": "runs_submission_export", "description": "Export submission for run."},
        ]
    }


def _tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    target = arguments.get("target")
    target_args = ["--target", str(target)] if target else []

    if name == "target_set":
        cli_args = [
            "target",
            "set",
            "--name",
            str(arguments.get("name", "local")),
            "--base-url",
            str(arguments["base_url"]),
        ]
        if bool(arguments.get("activate", True)):
            cli_args.append("--activate")
        return _run_expctl(cli_args)
    if name == "target_get":
        cli_args = ["target", "get"]
        if arguments.get("name"):
            cli_args.extend(["--name", str(arguments["name"])])
        return _run_expctl(cli_args)

    if name == "experiment_create":
        cli_args = [
            *target_args,
            "experiments",
            "compose",
            "--name",
            str(arguments["name"]),
            "--profile-id",
            str(arguments["profile_id"]),
        ]
        if arguments.get("gold_dataset_id"):
            cli_args.extend(["--gold-dataset-id", str(arguments["gold_dataset_id"])])
        if arguments.get("baseline_run_id"):
            cli_args.extend(["--baseline-run-id", str(arguments["baseline_run_id"])])
        return _run_expctl(cli_args)

    if name == "experiment_run":
        cli_args = [
            *target_args,
            "experiments",
            "run",
            "--experiment-id",
            str(arguments["experiment_id"]),
            "--stage-mode",
            str(arguments.get("stage_mode", "auto")),
            "--actor",
            str(arguments.get("actor", "mcp")),
            "--agent-mode",
        ]
        if arguments.get("baseline_run_id"):
            cli_args.extend(["--baseline-run-id", str(arguments["baseline_run_id"])])
        if arguments.get("proxy_sample_size") is not None:
            cli_args.extend(["--proxy-sample-size", str(arguments["proxy_sample_size"])])
        if arguments.get("idempotency_key"):
            cli_args.extend(["--idempotency-key", str(arguments["idempotency_key"])])
        return _run_expctl(cli_args)

    if name == "experiment_status":
        return _run_expctl(
            [
                *target_args,
                "experiments",
                "status",
                "--experiment-run-id",
                str(arguments["experiment_run_id"]),
            ]
        )
    if name == "experiment_analysis":
        return _run_expctl(
            [
                *target_args,
                "experiments",
                "analysis",
                "--experiment-run-id",
                str(arguments["experiment_run_id"]),
            ]
        )
    if name == "experiment_compare":
        return _run_expctl(
            [
                *target_args,
                "experiments",
                "compare",
                "--left-run-id",
                str(arguments["left_run_id"]),
                "--right-run-id",
                str(arguments["right_run_id"]),
            ]
        )
    if name == "leaderboard_get":
        cli_args = [*target_args, "experiments", "leaderboard"]
        if arguments.get("limit") is not None:
            cli_args.extend(["--limit", str(arguments["limit"])])
        if arguments.get("stage_type"):
            cli_args.extend(["--stage-type", str(arguments["stage_type"])])
        if arguments.get("experiment_id"):
            cli_args.extend(["--experiment-id", str(arguments["experiment_id"])])
        return _run_expctl(cli_args)

    if name == "qa_batch_run":
        payload = json.dumps(arguments["payload"], ensure_ascii=False)
        return _run_expctl([*target_args, "qa", "ask-batch", "--payload-json", payload])
    if name == "eval_run_create":
        payload = json.dumps(arguments["payload"], ensure_ascii=False)
        return _run_expctl([*target_args, "eval", "create", "--payload-json", payload])
    if name == "eval_report_get":
        return _run_expctl(
            [*target_args, "eval", "report", "--eval-run-id", str(arguments["eval_run_id"])]
        )
    if name == "gold_dataset_export":
        return _run_expctl(
            [*target_args, "gold", "export", "--gold-dataset-id", str(arguments["gold_dataset_id"])]
        )
    if name == "runs_submission_export":
        cli_args = [
            *target_args,
            "runs",
            "export-submission",
            "--run-id",
            str(arguments["run_id"]),
            "--page-index-base",
            str(arguments.get("page_index_base", 0)),
        ]
        return _run_expctl(cli_args)

    return {
        "error": {
            "code": "unknown_tool",
            "message": f"unsupported tool: {name}",
        }
    }


def _handle_json_rpc(payload: Dict[str, Any]) -> Dict[str, Any]:
    method = str(payload.get("method", ""))
    params = payload.get("params", {}) if isinstance(payload.get("params"), dict) else {}
    if method in {"tools/list", "list_tools"}:
        return {"ok": True, **_tool_list()}
    if method in {"tools/call", "call_tool"}:
        name = str(params.get("name", ""))
        args = params.get("arguments", {})
        if not isinstance(args, dict):
            args = {}
        result = _tool_call(name, args)
        if "error" in result:
            return {"ok": False, **result}
        return {"ok": True, **result}
    return {"ok": False, "error": {"code": "unknown_method", "message": method}}


def _stdio_loop() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("input must be json object")
        except Exception as exc:
            print(json.dumps({"ok": False, "error": {"code": "invalid_json", "message": str(exc)}}), flush=True)
            continue
        response = _handle_json_rpc(payload)
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="MCP adapter over expctl")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--tool", default=None)
    parser.add_argument("--args-json", default="{}")
    parser.add_argument("--stdio", action="store_true", help="line-delimited JSON RPC mode")
    args = parser.parse_args(argv[1:])

    if args.list_tools:
        print(json.dumps(_tool_list(), ensure_ascii=False, indent=2))
        return 0
    if args.stdio:
        return _stdio_loop()
    if args.tool:
        try:
            parsed_args = json.loads(args.args_json)
            if not isinstance(parsed_args, dict):
                raise ValueError("args-json must be object")
        except Exception as exc:
            print(json.dumps({"error": {"code": "invalid_args", "message": str(exc)}}))
            return 1
        result = _tool_call(args.tool, parsed_args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if "error" not in result else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

