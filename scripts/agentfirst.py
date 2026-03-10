#!/usr/bin/env python3
"""AgentFirst local harness helper.

Goal: give agents and humans one consistent entrypoint for validation.
This is intentionally lightweight and stack-agnostic.

Usage:
  python scripts/agentfirst.py detect
  python scripts/agentfirst.py verify [--strict]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # optional; script still works with auto-detection only

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".agentfirst" / "stack.yaml"

def _load_stack_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _detect_node() -> dict:
    pkg = ROOT / "package.json"
    if not pkg.exists():
        return {}
    try:
        pkg_json = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:
        return {}
    scripts = (pkg_json.get("scripts") or {}) if isinstance(pkg_json, dict) else {}
    if not isinstance(scripts, dict):
        scripts = {}
    # pick package manager
    if (ROOT / "pnpm-lock.yaml").exists():
        pm = "pnpm"
    elif (ROOT / "yarn.lock").exists():
        pm = "yarn"
    else:
        pm = "npm"

    def cmd_for(script_name: str) -> str:
        if pm == "npm":
            if script_name == "test":
                return "npm test"
            return f"npm run {script_name}"
        if pm == "pnpm":
            if script_name == "test":
                return "pnpm test"
            return f"pnpm run {script_name}"
        # yarn
        if script_name == "test":
            return "yarn test"
        return f"yarn {script_name}"

    out = {}
    for key in ["lint", "typecheck", "test", "build"]:
        if key in scripts:
            out[key] = cmd_for(key)

    # Best-effort: format check naming conventions
    for fmt_key in ["format:check", "fmt:check", "format_check", "formatcheck"]:
        if fmt_key in scripts:
            out["format_check"] = cmd_for(fmt_key)
            break

    out["_detected"] = "node"
    out["_package_manager"] = pm
    return out

def _detect_python() -> dict:
    # very conservative; many repos differ
    has_py = any((ROOT / p).exists() for p in ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"])
    if not has_py:
        return {}
    out = {"_detected": "python"}
    # Prefer uv/poetry if present
    if (ROOT / "uv.lock").exists():
        runner = "uv run"
    elif (ROOT / "poetry.lock").exists():
        runner = "poetry run"
    else:
        runner = "python -m"

    # test detection
    if (ROOT / "tests").exists():
        out["test"] = f"{runner} pytest"
    # lint detection
    if (ROOT / "ruff.toml").exists() or (ROOT / ".ruff.toml").exists() or (ROOT / "pyproject.toml").exists():
        # can't know if ruff installed; still try
        out["lint"] = f"{runner} ruff check ."
    # typecheck detection
    if (ROOT / "pyrightconfig.json").exists():
        out["typecheck"] = f"{runner} pyright"
    elif (ROOT / "mypy.ini").exists():
        out["typecheck"] = f"{runner} mypy ."
    return out

def resolve_commands() -> dict:
    cfg = _load_stack_config()
    cfg_cmds = (cfg.get("commands") or {}) if isinstance(cfg, dict) else {}
    cfg_cmds = cfg_cmds if isinstance(cfg_cmds, dict) else {}

    detected = {}
    # if user configured anything non-empty -> prefer config
    if any(str(v).strip() for v in cfg_cmds.values()):
        detected = {k: str(v).strip() for k, v in cfg_cmds.items() if str(v).strip()}
        detected["_source"] = "stack.yaml"
        return detected

    # else: attempt auto-detect, but keep it conservative
    for det in (_detect_node(), _detect_python()):
        if det:
            detected.update({k: v for k, v in det.items() if isinstance(v, str) and v.strip()})
            detected["_source"] = det.get("_detected", "auto")
    return detected

def run_cmd(cmd: str) -> int:
    print(f"\n==> {cmd}")
    proc = subprocess.run(cmd, shell=True, cwd=str(ROOT))
    return int(proc.returncode)

def cmd_detect() -> int:
    cmds = resolve_commands()
    print(json.dumps(cmds, indent=2, ensure_ascii=False))
    if not any(k in cmds for k in ["test", "lint", "typecheck", "build", "format_check"]):
        print("\n[warn] No validation commands resolved. Configure .agentfirst/stack.yaml.", file=sys.stderr)
        return 2
    return 0

def cmd_verify(strict: bool) -> int:
    cmds = resolve_commands()
    steps = []
    for k in ["format_check", "lint", "typecheck", "test", "build"]:
        if k in cmds:
            steps.append((k, cmds[k]))

    if not steps:
        print("No validation steps configured. Configure .agentfirst/stack.yaml or ensure your repo is detectable.", file=sys.stderr)
        return 2

    # minimal guardrail: require at least test OR lint in strict mode
    if strict and not any(k in cmds for k in ["test", "lint"]):
        print("Strict mode requires at least 'test' or 'lint' command.", file=sys.stderr)
        return 2

    for name, cmd in steps:
        rc = run_cmd(cmd)
        if rc != 0:
            print(f"[fail] Step '{name}' failed with exit code {rc}", file=sys.stderr)
            return rc
    print("\n[ok] verify passed")
    return 0

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: agentfirst.py <detect|verify> [--strict]", file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "detect":
        return cmd_detect()
    if cmd == "verify":
        strict = "--strict" in argv
        return cmd_verify(strict=strict)
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
