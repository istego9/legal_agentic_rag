from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import select_pilot_gold_subset as module  # noqa: E402


def test_build_selection_returns_25_and_counts_substitutions() -> None:
    triage_rows = []
    for index in range(8):
        triage_rows.append(
            {
                "question_id": f"law-article-{index}",
                "severity_score": 150 - index,
                "severity_label": "critical",
                "question_profile": {"normalized_taxonomy_route": "law_article_lookup", "target_doc_types_guess": ["law"]},
            }
        )
    for index in range(4):
        triage_rows.append(
            {
                "question_id": f"law-history-{index}",
                "severity_score": 140 - index,
                "severity_label": "critical",
                "question_profile": {"normalized_taxonomy_route": "law_relation_or_history", "target_doc_types_guess": ["law"]},
            }
        )
    triage_rows.append(
        {
            "question_id": "cross-law-0",
            "severity_score": 139,
            "severity_label": "critical",
            "question_profile": {"normalized_taxonomy_route": "law_article_lookup", "target_doc_types_guess": ["law"]},
        }
    )
    for name, route in [("case-entity", "case_entity_lookup"), ("case-value", "case_outcome_or_value"), ("case-compare", "case_cross_compare")]:
        triage_rows.append(
            {
                "question_id": name,
                "severity_score": 130,
                "severity_label": "critical",
                "question_profile": {"normalized_taxonomy_route": route, "target_doc_types_guess": ["case"]},
            }
        )
    for index in range(4):
        triage_rows.append(
            {
                "question_id": f"negative-{index}",
                "severity_score": 0,
                "severity_label": "low",
                "question_profile": {"normalized_taxonomy_route": "negative_or_unanswerable", "target_doc_types_guess": ["case"]},
            }
        )
    for index in range(10):
        triage_rows.append(
            {
                "question_id": f"scope-{index}",
                "severity_score": 120 - index,
                "severity_label": "critical",
                "question_profile": {"normalized_taxonomy_route": "law_scope_or_definition", "target_doc_types_guess": ["law"]},
            }
        )
    questions_by_id = {}
    for row in triage_rows:
        qid = row["question_id"]
        if qid.startswith("cross-law"):
            question = "According to Article 12(4) of one law and Article 18(2)(b) of another law, what are the retention periods?"
            answer_type = "free_text"
        elif qid.startswith("law-history"):
            question = "When was the consolidated version of the law published?"
            answer_type = "date"
        elif qid.startswith("law-article"):
            question = "Under Article 8(1), is the act permitted?"
            answer_type = "boolean"
        elif qid.startswith("case-entity"):
            question = "Who is the claimant in case CFI 010/2024?"
            answer_type = "name"
        elif qid.startswith("case-value"):
            question = "What was the claim value in case CA 005/2025?"
            answer_type = "number"
        elif qid.startswith("case-compare"):
            question = "Which case had the earlier issue date?"
            answer_type = "name"
        elif qid.startswith("negative"):
            question = "What Miranda rights warning was given?"
            answer_type = "free_text"
        else:
            question = "According to the title page, what is the official law number?"
            answer_type = "number"
        questions_by_id[qid] = {"id": qid, "question": question, "answer_type": answer_type}

    rows, metadata = module.build_selection(questions_by_id=questions_by_id, triage_rows=triage_rows)

    assert len(rows) == 25
    assert len({row["question_id"] for row in rows}) == 25
    assert metadata["composition"]["law_article_lookup"] == 8
    assert metadata["composition"]["law_relation_or_history"] == 4
    assert metadata["composition"]["cross_law_compare"] == 1
    assert metadata["composition"]["case_family"] == 3
    assert metadata["composition"]["negative_or_unanswerable"] == 4
    assert metadata["composition"]["law_scope_or_definition"] == 5


def test_report_mentions_unavoidable_imbalances() -> None:
    rows = [
        {
            "question_id": "q1",
            "question": "Question 1",
            "answer_type": "boolean",
            "route_family": "law_article_lookup",
            "selection_reason": "reason",
            "risk_tier": "high",
        }
    ]
    report = module.render_report(
        rows,
        {"selection_version": module.SELECTION_VERSION, "deviations": ["cross_law_compare missing"], "high_risk_count": 1},
        artifact_root=Path("/tmp/example"),
        questions_path=Path("/tmp/questions.json"),
    )
    assert "Unavoidable Imbalances" in report
    assert "cross_law_compare missing" in report


def test_main_writes_subset_and_report(tmp_path: Path) -> None:
    artifact_root = tmp_path / "baseline"
    artifact_root.mkdir(parents=True)
    triage_rows = []
    questions = []
    for i in range(25):
        qid = f"q{i}"
        route = "negative_or_unanswerable" if i < 4 else "law_scope_or_definition"
        if i >= 4:
            question = f"According to the title page, what is official law number {i}?"
            answer_type = "number"
        else:
            question = f"What jury verdict was returned in case {i}?"
            answer_type = "free_text"
        questions.append({"id": qid, "question": question, "answer_type": answer_type})
        triage_rows.append(
            {
                "question_id": qid,
                "severity_score": 100,
                "severity_label": "critical",
                "question_profile": {"normalized_taxonomy_route": route, "target_doc_types_guess": ["law"]},
            }
        )
    # Patch in enough required categories by hand.
    triage_rows[:8] = [
        {"question_id": f"la{i}", "severity_score": 150, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "law_article_lookup", "target_doc_types_guess": ["law"]}}
        for i in range(8)
    ]
    triage_rows[8:12] = [
        {"question_id": f"lh{i}", "severity_score": 140, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "law_relation_or_history", "target_doc_types_guess": ["law"]}}
        for i in range(4)
    ]
    triage_rows[12] = {"question_id": "cl0", "severity_score": 139, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "law_article_lookup", "target_doc_types_guess": ["law"]}}
    triage_rows[13:16] = [
        {"question_id": "ce", "severity_score": 130, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "case_entity_lookup", "target_doc_types_guess": ["case"]}},
        {"question_id": "co", "severity_score": 130, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "case_outcome_or_value", "target_doc_types_guess": ["case"]}},
        {"question_id": "cc", "severity_score": 130, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "case_cross_compare", "target_doc_types_guess": ["case"]}},
    ]
    triage_rows[16:20] = [
        {"question_id": f"neg{i}", "severity_score": 0, "severity_label": "low", "question_profile": {"normalized_taxonomy_route": "negative_or_unanswerable", "target_doc_types_guess": ["case"]}}
        for i in range(4)
    ]
    triage_rows[20:25] = [
        {"question_id": f"ls{i}", "severity_score": 120, "severity_label": "critical", "question_profile": {"normalized_taxonomy_route": "law_scope_or_definition", "target_doc_types_guess": ["law"]}}
        for i in range(5)
    ]
    questions = []
    for row in triage_rows:
        qid = row["question_id"]
        if qid.startswith("la"):
            question = "Under Article 8(1), is the act permitted?"
            answer_type = "boolean"
        elif qid.startswith("lh"):
            question = "When was the consolidated version published?"
            answer_type = "date"
        elif qid == "cl0":
            question = "According to Article 12(4) of one law and Article 18(2)(b) of another law, what are the retention periods?"
            answer_type = "free_text"
        elif qid in {"ce", "co", "cc"}:
            question = "Which case had the earlier issue date?" if qid == "cc" else "Who is the claimant?" if qid == "ce" else "What was the claim value?"
            answer_type = "name" if qid in {"ce", "cc"} else "number"
        elif qid.startswith("neg"):
            question = "What Miranda rights warning was given?"
            answer_type = "free_text"
        else:
            question = "According to the title page, what is the official law number?"
            answer_type = "number"
        questions.append({"id": qid, "question": question, "answer_type": answer_type})
    (artifact_root / "triage_queue.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in triage_rows) + "\n",
        encoding="utf-8",
    )
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path = tmp_path / "pilot_gold_questions_v1.jsonl"
    report_path = tmp_path / "pilot_gold_selection_report.md"

    rc = module.main(
        ["--artifact-root", str(artifact_root), "--questions", str(questions_path), "--output", str(output_path), "--report", str(report_path)]
    )
    assert rc == 0
    assert output_path.exists()
    assert report_path.exists()
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 25
