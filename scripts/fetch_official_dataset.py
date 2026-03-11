#!/usr/bin/env python3
"""Download the official competition questions/documents bundle using API key auth.

Usage:
  EVAL_API_KEY=... .venv/bin/python scripts/fetch_official_dataset.py
  AGENTIC_CHALLENGE_API_KEY=... .venv/bin/python scripts/fetch_official_dataset.py --output-dir datasets/official_fetch_local
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://platform.agentic-challenge.ai/api/v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(*, url: str, api_key: str, out_path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "X-API-Key": api_key,
            "Accept": "application/octet-stream,application/json",
            "User-Agent": "legal-agentic-rag/fetch-official-dataset",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed URL from args/env
        payload = response.read()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)


def _build_manifest(*, base_url: str, output_dir: Path, questions_path: Path, documents_path: Path) -> dict[str, Any]:
    questions_payload = json.loads(questions_path.read_text(encoding="utf-8"))
    questions_count = len(questions_payload) if isinstance(questions_payload, list) else None
    return {
        "source": {
            "base_url": base_url.rstrip("/"),
            "questions_endpoint": "/questions",
            "documents_endpoint": "/documents",
        },
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "artifacts": {
            "questions": {
                "path": str(questions_path),
                "bytes": questions_path.stat().st_size,
                "sha256": _sha256(questions_path),
                "question_count": questions_count,
            },
            "documents_zip": {
                "path": str(documents_path),
                "bytes": documents_path.stat().st_size,
                "sha256": _sha256(documents_path),
            },
        },
        "notes": [
            "Do not commit downloaded bundles unless organizer policy explicitly allows redistribution.",
            "Use this manifest to verify local files after fetch.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch official dataset bundle via platform API")
    parser.add_argument(
        "--base-url",
        default=os.getenv("EVAL_BASE_URL", DEFAULT_BASE_URL),
        help="Evaluation API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("EVAL_API_KEY") or os.getenv("AGENTIC_CHALLENGE_API_KEY"),
        help="API key (or set EVAL_API_KEY / AGENTIC_CHALLENGE_API_KEY)",
    )
    parser.add_argument(
        "--output-dir",
        default="datasets/official_fetch_local",
        help="Output directory for downloaded artifacts (default: %(default)s)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files if present",
    )
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Set EVAL_API_KEY or AGENTIC_CHALLENGE_API_KEY, or pass --api-key.")

    output_dir = Path(args.output_dir).resolve()
    questions_path = output_dir / "questions.json"
    documents_path = output_dir / "documents.zip"
    manifest_path = output_dir / "manifest.json"

    if not args.overwrite and (questions_path.exists() or documents_path.exists()):
        raise SystemExit(
            f"Output files already exist under {output_dir}. "
            "Use --overwrite or choose a different --output-dir."
        )

    base_url = str(args.base_url).rstrip("/")
    try:
        _download_file(url=f"{base_url}/questions", api_key=args.api_key, out_path=questions_path)
        _download_file(url=f"{base_url}/documents", api_key=args.api_key, out_path=documents_path)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        raise SystemExit(f"Download failed with HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network dependent
        raise SystemExit(f"Download failed: {exc.reason}") from exc

    manifest = _build_manifest(
        base_url=base_url,
        output_dir=output_dir,
        questions_path=questions_path,
        documents_path=documents_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
