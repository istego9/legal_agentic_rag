"""Scoring primitives used by eval pipeline."""

from .contracts import (
    blocking_failure_histogram,
    build_scorer_summary_markdown,
    evaluate_query_response_contract,
    strict_competition_contracts_enabled,
    submission_contract_preflight,
)
from .metrics import fbeta_precision_recall, overlap_stats

__all__ = [
    "fbeta_precision_recall",
    "overlap_stats",
    "evaluate_query_response_contract",
    "build_scorer_summary_markdown",
    "submission_contract_preflight",
    "strict_competition_contracts_enabled",
    "blocking_failure_histogram",
]
