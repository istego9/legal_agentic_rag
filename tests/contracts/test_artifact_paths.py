from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import artifacts as artifacts_module  # noqa: E402


def test_artifacts_root_defaults_to_hidden_repo_local_dir(monkeypatch) -> None:
    monkeypatch.delenv("LEGAL_RAG_ARTIFACTS_ROOT", raising=False)
    assert artifacts_module.artifacts_root() == (ROOT / ".artifacts").resolve()


def test_artifacts_root_honors_env_override(monkeypatch, tmp_path: Path) -> None:
    custom_root = tmp_path / "legal-rag-artifacts"
    monkeypatch.setenv("LEGAL_RAG_ARTIFACTS_ROOT", str(custom_root))
    assert artifacts_module.artifacts_root() == custom_root.resolve()
    assert artifacts_module.artifact_path("competition_runs").parent == custom_root.resolve()
