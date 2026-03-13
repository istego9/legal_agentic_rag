from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import adjudicate_pilot_gold as module  # noqa: E402


def test_agreement_state_detects_consensus_disagreement_and_abstain() -> None:
    consensus = [
        {"candidate_kind": "system", "answer": 7, "answerability": "answerable", "sources": [{"source_page_id": "doc_1"}]},
        {"candidate_kind": "strong_model", "answer": 7, "answerability": "answerable", "sources": [{"source_page_id": "doc_1"}]},
    ]
    disagreement = [
        {"candidate_kind": "system", "answer": 7, "answerability": "answerable", "sources": [{"source_page_id": "doc_1"}]},
        {"candidate_kind": "strong_model", "answer": 14, "answerability": "answerable", "sources": [{"source_page_id": "doc_2"}]},
    ]
    all_abstain = [
        {"candidate_kind": "system", "answer": None, "answerability": "abstain", "sources": []},
        {"candidate_kind": "strong_model", "answer": None, "answerability": "abstain", "sources": []},
    ]

    assert module._agreement_state(consensus) == "consensus"
    assert module._agreement_state(disagreement) == "disagreement"
    assert module._agreement_state(all_abstain) == "all_abstain"


def test_preferred_candidate_prefers_consensus_and_system_fallback() -> None:
    consensus = [
        {"candidate_kind": "system", "answer": 7, "answerability": "answerable", "sources": [{"source_page_id": "doc_1"}]},
        {"candidate_kind": "strong_model", "answer": 7, "answerability": "answerable", "sources": [{"source_page_id": "doc_1"}]},
    ]
    single = [
        {"candidate_kind": "system", "answer": "Registrar", "answerability": "answerable", "sources": [{"source_page_id": "doc_1"}]},
        {"candidate_kind": "strong_model", "answer": None, "answerability": "abstain", "sources": []},
    ]

    assert module._preferred_candidate(consensus) == "system"
    assert module._preferred_candidate(single) == "system"


def test_build_report_mentions_locked_and_blockers() -> None:
    report = module._build_report(
        locked_count=5,
        unresolved_count=20,
        disagreement_histogram=module.Counter({"answer_conflict": 3}),
        reason_histogram=module.Counter({"locked_from_grounded_candidate": 5, "no_grounded_candidate_consensus": 20}),
        blockers=["blocker one", "blocker two"],
        artifact_dir=Path("/tmp/pilot"),
        run_id="run-1",
        gold_dataset_id="gold-1",
    )
    assert "locked_count: `5`" in report
    assert "unresolved_count: `20`" in report
    assert "answer_conflict" in report
    assert "blocker one" in report
