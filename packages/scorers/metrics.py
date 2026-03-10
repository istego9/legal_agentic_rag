"""Scorers for answer correctness and source overlap."""

from __future__ import annotations

from typing import Iterable, Set


def fbeta_precision_recall(
    true_pos: int,
    pred_total: int,
    gold_total: int,
    beta: float = 2.5,
) -> float:
    if pred_total == 0 and gold_total == 0:
        return 1.0
    if pred_total == 0 or gold_total == 0:
        return 0.0
    precision = true_pos / pred_total
    recall = true_pos / gold_total
    if precision == 0 and recall == 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def overlap_stats(
    predicted: Iterable[str],
    gold: Iterable[str],
    *,
    beta: float = 2.5,
) -> tuple[float, float, float]:
    p_set: Set[str] = set(predicted)
    g_set: Set[str] = set(gold)
    if not p_set and not g_set:
        return 1.0, 1.0, 1.0
    if not p_set or not g_set:
        return 0.0, 0.0, 0.0
    tp = len(p_set.intersection(g_set))
    precision = tp / len(p_set)
    recall = tp / len(g_set)
    f = fbeta_precision_recall(tp, len(p_set), len(g_set), beta=beta)
    return precision, recall, f
