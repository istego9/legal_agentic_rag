from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ARTIFACTS_ROOT = (REPO_ROOT / ".artifacts").resolve()


def artifacts_root() -> Path:
    raw = str(os.getenv("LEGAL_RAG_ARTIFACTS_ROOT", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_ARTIFACTS_ROOT


def artifact_path(*parts: str) -> Path:
    return artifacts_root().joinpath(*parts)


def ensure_artifact_dir(*parts: str) -> Path:
    path = artifact_path(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_uri(path: Path) -> str:
    return path.resolve().as_uri()
