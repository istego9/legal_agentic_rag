#!/usr/bin/env python3
"""CLI-first operator console for experiment platform and existing API surfaces."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional
from urllib import error, parse, request


DEFAULT_TARGET = "local"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def _config_path() -> Path:
    raw = os.getenv("EXPCTL_CONFIG_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / ".expctl" / "targets.json"


def _load_cfg() -> Dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {
            "active": DEFAULT_TARGET,
            "targets": {
                DEFAULT_TARGET: {
                    "base_url": DEFAULT_BASE_URL,
                }
            },
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "active": DEFAULT_TARGET,
            "targets": {
                DEFAULT_TARGET: {
                    "base_url": DEFAULT_BASE_URL,
                }
            },
        }
    if not isinstance(data, dict):
        return {"active": DEFAULT_TARGET, "targets": {}}
    data.setdefault("active", DEFAULT_TARGET)
    data.setdefault("targets", {})
    if not data["targets"]:
        data["targets"][DEFAULT_TARGET] = {"base_url": DEFAULT_BASE_URL}
    return data


def _save_cfg(cfg: Dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _target_resolve(cfg: Dict[str, Any], target_override: Optional[str]) -> Dict[str, Any]:
    target_name = target_override or str(cfg.get("active", DEFAULT_TARGET))
    targets = cfg.get("targets", {})
    target = targets.get(target_name)
    if not isinstance(target, dict):
        raise RuntimeError(f"target '{target_name}' is not configured")
    base_url = str(target.get("base_url", "")).strip()
    if not base_url:
        raise RuntimeError(f"target '{target_name}' has empty base_url")
    return {"name": target_name, "base_url": base_url.rstrip("/")}


def _load_payload(payload_json: Optional[str], payload_file: Optional[str], default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if payload_file:
        data = json.loads(Path(payload_file).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("payload file must contain JSON object")
        return data
    if payload_json:
        data = json.loads(payload_json)
        if not isinstance(data, dict):
            raise RuntimeError("payload JSON must be object")
        return data
    return default or {}


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    qs = ""
    if query:
        encoded = {k: str(v) for k, v in query.items() if v is not None}
        if encoded:
            qs = "?" + parse.urlencode(encoded)
    url = f"{base_url}{path}{qs}"
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None and method.upper() in {"POST", "PUT", "PATCH"}:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = request.Request(url=url, method=method.upper(), headers=headers, data=data)
    try:
        with request.urlopen(req, timeout=300) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_body = json.loads(body) if body else {}
        except Exception:
            parsed_body = {"raw": body}
        return {"error": {"status": exc.code, "body": parsed_body, "url": url}}
    except Exception as exc:
        return {"error": {"status": 0, "message": str(exc), "url": url}}


def _print(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _target_command(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _load_cfg()
    if args.target_cmd == "list":
        return {"active": cfg.get("active"), "targets": cfg.get("targets", {})}
    if args.target_cmd == "get":
        name = args.name or cfg.get("active")
        target = (cfg.get("targets") or {}).get(name)
        if not target:
            return {"error": {"status": 404, "message": f"target '{name}' not found"}}
        return {"name": name, "active": cfg.get("active") == name, "target": target}
    if args.target_cmd == "set":
        cfg.setdefault("targets", {})
        cfg["targets"][args.name] = {"base_url": args.base_url}
        if args.activate or not cfg.get("active"):
            cfg["active"] = args.name
        _save_cfg(cfg)
        return {"status": "ok", "active": cfg.get("active"), "targets": cfg.get("targets")}
    return {"error": {"status": 422, "message": "unknown target command"}}


def _experiments_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.exp_cmd
    if cmd == "profiles-create":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {
                "name": args.name,
                "project_id": args.project_id,
                "dataset_id": args.dataset_id,
                "gold_dataset_id": args.gold_dataset_id,
                "endpoint_target": args.endpoint_target,
                "active": True,
            },
        )
        return _request_json(base, "POST", "/v1/experiments/profiles", payload=payload, idempotency_key=args.idempotency_key)
    if cmd == "profiles-list":
        return _request_json(base, "GET", "/v1/experiments/profiles", query={"limit": args.limit})
    if cmd == "compose":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {
                "name": args.name,
                "profile_id": args.profile_id,
                "gold_dataset_id": args.gold_dataset_id,
                "baseline_experiment_run_id": args.baseline_run_id,
                "metadata": {},
            },
        )
        return _request_json(base, "POST", "/v1/experiments", payload=payload, idempotency_key=args.idempotency_key)
    if cmd == "get":
        return _request_json(base, "GET", f"/v1/experiments/{args.experiment_id}")
    if cmd == "run":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {
                "stage_mode": args.stage_mode,
                "baseline_experiment_run_id": args.baseline_run_id,
                "proxy_sample_size": args.proxy_sample_size,
                "actor": args.actor,
                "agent_mode": args.agent_mode,
                "idempotency_key": args.idempotency_key,
            },
        )
        return _request_json(
            base,
            "POST",
            f"/v1/experiments/{args.experiment_id}/runs",
            payload=payload,
            idempotency_key=args.idempotency_key,
        )
    if cmd == "status":
        return _request_json(base, "GET", f"/v1/experiments/runs/{args.experiment_run_id}")
    if cmd == "analysis":
        return _request_json(base, "GET", f"/v1/experiments/runs/{args.experiment_run_id}/analysis")
    if cmd == "compare":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {
                "left_experiment_run_id": args.left_run_id,
                "right_experiment_run_id": args.right_run_id,
            },
        )
        return _request_json(base, "POST", "/v1/experiments/compare", payload=payload)
    if cmd == "leaderboard":
        return _request_json(
            base,
            "GET",
            "/v1/experiments/leaderboard",
            query={
                "limit": args.limit,
                "stage_type": args.stage_type,
                "experiment_id": args.experiment_id,
            },
        )
    return {"error": {"status": 422, "message": "unknown experiments command"}}


def _corpus_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.corpus_cmd
    if cmd == "import":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {
                "project_id": args.project_id,
                "blob_url": args.blob_url,
                "parse_policy": args.parse_policy,
                "dedupe_enabled": args.dedupe_enabled,
            },
        )
        return _request_json(base, "POST", "/v1/corpus/import-zip", payload=payload, idempotency_key=args.idempotency_key)
    if cmd in {"list", "docs"}:
        return _request_json(
            base,
            "GET",
            "/v1/corpus/documents",
            query={"project_id": args.project_id, "limit": args.limit},
        )
    if cmd == "pages":
        detail = _request_json(base, "GET", f"/v1/corpus/documents/{args.document_id}/detail")
        if "error" in detail:
            return detail
        return {"document_id": args.document_id, "pages": detail.get("pages", [])}
    if cmd == "paragraphs":
        return _request_json(
            base,
            "GET",
            "/v1/corpus/chunks",
            query={"project_id": args.project_id, "document_id": args.document_id, "limit": args.limit},
        )
    if cmd == "search":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {
                "project_id": args.project_id,
                "query": args.query,
                "search_profile": args.search_profile,
                "top_k": args.top_k,
            },
        )
        return _request_json(base, "POST", "/v1/corpus/search", payload=payload)
    if cmd == "processing-results":
        return _request_json(
            base,
            "GET",
            "/v1/corpus/processing-results",
            query={"project_id": args.project_id, "limit": args.limit},
        )
    return {"error": {"status": 422, "message": "unknown corpus command"}}


def _qa_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.qa_cmd
    if cmd == "ask":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/qa/ask", payload=payload)
    if cmd == "ask-batch":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/qa/ask-batch", payload=payload, idempotency_key=args.idempotency_key)
    if cmd == "list-questions":
        return _request_json(base, "GET", f"/v1/qa/datasets/{args.dataset_id}/questions", query={"limit": args.limit})
    if cmd == "import-questions":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(
            base,
            "POST",
            f"/v1/qa/datasets/{args.dataset_id}/import-questions",
            payload=payload,
            idempotency_key=args.idempotency_key,
        )
    return {"error": {"status": 422, "message": "unknown qa command"}}


def _runs_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.runs_cmd
    if cmd == "get":
        return _request_json(base, "GET", f"/v1/runs/{args.run_id}")
    if cmd == "run-question":
        return _request_json(base, "GET", f"/v1/runs/{args.run_id}/questions/{args.question_id}")
    if cmd == "export-submission":
        payload = _load_payload(args.payload_json, args.payload_file, {"page_index_base": args.page_index_base})
        return _request_json(base, "POST", f"/v1/runs/{args.run_id}/export-submission", payload=payload)
    return {"error": {"status": 422, "message": "unknown runs command"}}


def _eval_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.eval_cmd
    if cmd == "create":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/eval/runs", payload=payload, idempotency_key=args.idempotency_key)
    if cmd == "get":
        return _request_json(base, "GET", f"/v1/eval/runs/{args.eval_run_id}")
    if cmd == "report":
        return _request_json(base, "GET", f"/v1/eval/runs/{args.eval_run_id}/report")
    if cmd == "compare":
        payload = _load_payload(
            args.payload_json,
            args.payload_file,
            {"left_eval_run_id": args.left_eval_run_id, "right_eval_run_id": args.right_eval_run_id},
        )
        return _request_json(base, "POST", "/v1/eval/compare", payload=payload)
    if cmd == "calibrate":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/eval/calibrate-judge", payload=payload, idempotency_key=args.idempotency_key)
    return {"error": {"status": 422, "message": "unknown eval command"}}


def _gold_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.gold_cmd
    if cmd == "datasets":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/gold/datasets", payload=payload, idempotency_key=args.idempotency_key)
    if cmd == "dataset-get":
        return _request_json(base, "GET", f"/v1/gold/datasets/{args.gold_dataset_id}")
    if cmd == "questions":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(
            base,
            "POST",
            f"/v1/gold/datasets/{args.gold_dataset_id}/questions",
            payload=payload,
            idempotency_key=args.idempotency_key,
        )
    if cmd == "review":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", f"/v1/gold/questions/{args.gold_question_id}/review", payload=payload)
    if cmd == "lock":
        payload = _load_payload(args.payload_json, args.payload_file, {})
        return _request_json(base, "POST", f"/v1/gold/datasets/{args.gold_dataset_id}/lock", payload=payload)
    if cmd == "export":
        return _request_json(base, "GET", f"/v1/gold/datasets/{args.gold_dataset_id}/export")
    return {"error": {"status": 422, "message": "unknown gold command"}}


def _synth_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.synth_cmd
    if cmd == "jobs":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/synth/jobs", payload=payload, idempotency_key=args.idempotency_key)
    if cmd == "preview":
        payload = _load_payload(args.payload_json, args.payload_file, {"limit": args.limit})
        return _request_json(base, "POST", f"/v1/synth/jobs/{args.job_id}/preview", payload=payload)
    if cmd == "approve":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", f"/v1/synth/items/{args.candidate_id}/approve", payload=payload)
    if cmd == "publish":
        payload = _load_payload(args.payload_json, args.payload_file, {})
        return _request_json(base, "POST", f"/v1/synth/jobs/{args.job_id}/publish", payload=payload)
    return {"error": {"status": 422, "message": "unknown synth command"}}


def _config_command(args: argparse.Namespace, target: Dict[str, Any]) -> Dict[str, Any]:
    base = target["base_url"]
    cmd = args.config_cmd
    if cmd == "scoring-policies-list":
        return _request_json(base, "GET", "/v1/config/scoring-policies")
    if cmd == "scoring-policies-upsert":
        payload = _load_payload(args.payload_json, args.payload_file)
        return _request_json(base, "POST", "/v1/config/scoring-policies", payload=payload, idempotency_key=args.idempotency_key)
    return {"error": {"status": 422, "message": "unknown config command"}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment platform CLI")
    parser.add_argument("--target", default=None, help="target profile name")
    parser.add_argument("--json", action="store_true", default=True, help="print JSON output (default)")
    parser.add_argument("--idempotency-key", default=None, help="idempotency key for mutating commands")

    sub = parser.add_subparsers(dest="group", required=True)

    target = sub.add_parser("target")
    target_sub = target.add_subparsers(dest="target_cmd", required=True)
    target_sub.add_parser("list")
    target_get = target_sub.add_parser("get")
    target_get.add_argument("--name", default=None)
    target_set = target_sub.add_parser("set")
    target_set.add_argument("--name", required=True)
    target_set.add_argument("--base-url", required=True)
    target_set.add_argument("--activate", action="store_true")

    exp = sub.add_parser("experiments")
    exp_sub = exp.add_subparsers(dest="exp_cmd", required=True)
    exp_pc = exp_sub.add_parser("profiles-create")
    exp_pc.add_argument("--name", required=True)
    exp_pc.add_argument("--project-id", required=True)
    exp_pc.add_argument("--dataset-id", required=True)
    exp_pc.add_argument("--gold-dataset-id", required=True)
    exp_pc.add_argument("--endpoint-target", default="local")
    exp_pc.add_argument("--payload-json", default=None)
    exp_pc.add_argument("--payload-file", default=None)
    exp_pl = exp_sub.add_parser("profiles-list")
    exp_pl.add_argument("--limit", type=int, default=50)
    exp_compose = exp_sub.add_parser("compose")
    exp_compose.add_argument("--name", required=True)
    exp_compose.add_argument("--profile-id", required=True)
    exp_compose.add_argument("--gold-dataset-id", default=None)
    exp_compose.add_argument("--baseline-run-id", default=None)
    exp_compose.add_argument("--payload-json", default=None)
    exp_compose.add_argument("--payload-file", default=None)
    exp_get = exp_sub.add_parser("get")
    exp_get.add_argument("--experiment-id", required=True)
    exp_run = exp_sub.add_parser("run")
    exp_run.add_argument("--experiment-id", required=True)
    exp_run.add_argument("--stage-mode", choices=["auto", "proxy", "full"], default="auto")
    exp_run.add_argument("--baseline-run-id", default=None)
    exp_run.add_argument("--proxy-sample-size", type=int, default=None)
    exp_run.add_argument("--actor", default="cli")
    exp_run.add_argument("--agent-mode", action="store_true")
    exp_run.add_argument("--payload-json", default=None)
    exp_run.add_argument("--payload-file", default=None)
    exp_status = exp_sub.add_parser("status")
    exp_status.add_argument("--experiment-run-id", required=True)
    exp_analysis = exp_sub.add_parser("analysis")
    exp_analysis.add_argument("--experiment-run-id", required=True)
    exp_compare = exp_sub.add_parser("compare")
    exp_compare.add_argument("--left-run-id", required=True)
    exp_compare.add_argument("--right-run-id", required=True)
    exp_compare.add_argument("--payload-json", default=None)
    exp_compare.add_argument("--payload-file", default=None)
    exp_lb = exp_sub.add_parser("leaderboard")
    exp_lb.add_argument("--limit", type=int, default=50)
    exp_lb.add_argument("--stage-type", default=None)
    exp_lb.add_argument("--experiment-id", default=None)

    corpus = sub.add_parser("corpus")
    corpus_sub = corpus.add_subparsers(dest="corpus_cmd", required=True)
    corpus_import = corpus_sub.add_parser("import")
    corpus_import.add_argument("--project-id", required=True)
    corpus_import.add_argument("--blob-url", required=True)
    corpus_import.add_argument("--parse-policy", default="balanced")
    corpus_import.add_argument("--dedupe-enabled", action="store_true", default=True)
    corpus_import.add_argument("--payload-json", default=None)
    corpus_import.add_argument("--payload-file", default=None)
    for name in ["list", "docs"]:
        c = corpus_sub.add_parser(name)
        c.add_argument("--project-id", default=None)
        c.add_argument("--limit", type=int, default=50)
    c_pages = corpus_sub.add_parser("pages")
    c_pages.add_argument("--document-id", required=True)
    c_para = corpus_sub.add_parser("paragraphs")
    c_para.add_argument("--project-id", required=True)
    c_para.add_argument("--document-id", default=None)
    c_para.add_argument("--limit", type=int, default=50)
    c_search = corpus_sub.add_parser("search")
    c_search.add_argument("--project-id", required=True)
    c_search.add_argument("--query", required=True)
    c_search.add_argument("--search-profile", default="default")
    c_search.add_argument("--top-k", type=int, default=20)
    c_search.add_argument("--payload-json", default=None)
    c_search.add_argument("--payload-file", default=None)
    c_proc = corpus_sub.add_parser("processing-results")
    c_proc.add_argument("--project-id", required=True)
    c_proc.add_argument("--limit", type=int, default=20)

    qa = sub.add_parser("qa")
    qa_sub = qa.add_subparsers(dest="qa_cmd", required=True)
    for name in ["ask", "ask-batch"]:
        q = qa_sub.add_parser(name)
        q.add_argument("--payload-json", default=None)
        q.add_argument("--payload-file", default=None)
    q_list = qa_sub.add_parser("list-questions")
    q_list.add_argument("--dataset-id", required=True)
    q_list.add_argument("--limit", type=int, default=100)
    q_import = qa_sub.add_parser("import-questions")
    q_import.add_argument("--dataset-id", required=True)
    q_import.add_argument("--payload-json", default=None)
    q_import.add_argument("--payload-file", default=None)

    runs = sub.add_parser("runs")
    runs_sub = runs.add_subparsers(dest="runs_cmd", required=True)
    r_get = runs_sub.add_parser("get")
    r_get.add_argument("--run-id", required=True)
    r_q = runs_sub.add_parser("run-question")
    r_q.add_argument("--run-id", required=True)
    r_q.add_argument("--question-id", required=True)
    r_export = runs_sub.add_parser("export-submission")
    r_export.add_argument("--run-id", required=True)
    r_export.add_argument("--page-index-base", type=int, default=0, choices=[0, 1])
    r_export.add_argument("--payload-json", default=None)
    r_export.add_argument("--payload-file", default=None)

    ev = sub.add_parser("eval")
    ev_sub = ev.add_subparsers(dest="eval_cmd", required=True)
    ev_create = ev_sub.add_parser("create")
    ev_create.add_argument("--payload-json", default=None)
    ev_create.add_argument("--payload-file", default=None)
    ev_get = ev_sub.add_parser("get")
    ev_get.add_argument("--eval-run-id", required=True)
    ev_report = ev_sub.add_parser("report")
    ev_report.add_argument("--eval-run-id", required=True)
    ev_compare = ev_sub.add_parser("compare")
    ev_compare.add_argument("--left-eval-run-id", required=True)
    ev_compare.add_argument("--right-eval-run-id", required=True)
    ev_compare.add_argument("--payload-json", default=None)
    ev_compare.add_argument("--payload-file", default=None)
    ev_cal = ev_sub.add_parser("calibrate")
    ev_cal.add_argument("--payload-json", default=None)
    ev_cal.add_argument("--payload-file", default=None)

    gold = sub.add_parser("gold")
    gold_sub = gold.add_subparsers(dest="gold_cmd", required=True)
    g_ds = gold_sub.add_parser("datasets")
    g_ds.add_argument("--payload-json", default=None)
    g_ds.add_argument("--payload-file", default=None)
    g_dg = gold_sub.add_parser("dataset-get")
    g_dg.add_argument("--gold-dataset-id", required=True)
    g_q = gold_sub.add_parser("questions")
    g_q.add_argument("--gold-dataset-id", required=True)
    g_q.add_argument("--payload-json", default=None)
    g_q.add_argument("--payload-file", default=None)
    g_review = gold_sub.add_parser("review")
    g_review.add_argument("--gold-question-id", required=True)
    g_review.add_argument("--payload-json", default=None)
    g_review.add_argument("--payload-file", default=None)
    g_lock = gold_sub.add_parser("lock")
    g_lock.add_argument("--gold-dataset-id", required=True)
    g_lock.add_argument("--payload-json", default=None)
    g_lock.add_argument("--payload-file", default=None)
    g_exp = gold_sub.add_parser("export")
    g_exp.add_argument("--gold-dataset-id", required=True)

    synth = sub.add_parser("synth")
    synth_sub = synth.add_subparsers(dest="synth_cmd", required=True)
    s_jobs = synth_sub.add_parser("jobs")
    s_jobs.add_argument("--payload-json", default=None)
    s_jobs.add_argument("--payload-file", default=None)
    s_prev = synth_sub.add_parser("preview")
    s_prev.add_argument("--job-id", required=True)
    s_prev.add_argument("--limit", type=int, default=20)
    s_prev.add_argument("--payload-json", default=None)
    s_prev.add_argument("--payload-file", default=None)
    s_app = synth_sub.add_parser("approve")
    s_app.add_argument("--candidate-id", required=True)
    s_app.add_argument("--payload-json", default=None)
    s_app.add_argument("--payload-file", default=None)
    s_pub = synth_sub.add_parser("publish")
    s_pub.add_argument("--job-id", required=True)
    s_pub.add_argument("--payload-json", default=None)
    s_pub.add_argument("--payload-file", default=None)

    cfg = sub.add_parser("config")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("scoring-policies-list")
    cfg_u = cfg_sub.add_parser("scoring-policies-upsert")
    cfg_u.add_argument("--payload-json", default=None)
    cfg_u.add_argument("--payload-file", default=None)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    cfg = _load_cfg()

    if args.group == "target":
        result = _target_command(args)
        _print(result)
        return 0 if "error" not in result else 1

    try:
        target = _target_resolve(cfg, args.target)
    except Exception as exc:
        _print({"error": {"status": 1, "message": str(exc)}})
        return 1

    if args.group == "experiments":
        result = _experiments_command(args, target)
    elif args.group == "corpus":
        result = _corpus_command(args, target)
    elif args.group == "qa":
        result = _qa_command(args, target)
    elif args.group == "runs":
        result = _runs_command(args, target)
    elif args.group == "eval":
        result = _eval_command(args, target)
    elif args.group == "gold":
        result = _gold_command(args, target)
    elif args.group == "synth":
        result = _synth_command(args, target)
    elif args.group == "config":
        result = _config_command(args, target)
    else:
        result = {"error": {"status": 422, "message": f"unsupported group: {args.group}"}}

    _print(result)
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

