"""Standard retrieval metrics over gold evidence units (evals/pinned-gold.json format).

A search result matches a gold unit when the page is equal and every evidence
condition the unit declares holds (whitespace-insensitive):
- literal_conditions: each phrase appears in the quote.
- table: a table_evidence fact equals every non-null gold field, or the gold
  row_label and value both appear in the quote.
- numeric: each item is a numeric_evidence fact equal on every gold field, or
  its value appears in the quote.
A unit with none of these matches on page alone. page_only=True skips the
evidence conditions.
"""
import re
from collections.abc import Iterable

CUTOFF = 5
HIT_LEVELS = (1, 3, 5)


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value))


def _fact_equals(fact: dict, expected: dict) -> bool:
    return all(compact(fact.get(key)) == compact(value) for key, value in expected.items() if value is not None)


def _table_holds(result: dict, table: dict) -> bool:
    if any(_fact_equals(fact, table) for fact in result.get("table_evidence") or []):
        return True
    quote = compact(result.get("quote", ""))
    return all(compact(table[key]) in quote for key in ("row_label", "value") if table.get(key) is not None)


def _numeric_holds(result: dict, items: list[dict]) -> bool:
    facts = result.get("numeric_evidence") or []
    quote = compact(result.get("quote", ""))
    return all(any(_fact_equals(fact, item) for fact in facts) or compact(item["value"]) in quote for item in items)


def unit_matches(result: dict, unit: dict, *, page_only: bool = False) -> bool:
    if result.get("page_number") != unit.get("page_number"):
        return False
    if page_only:
        return True
    quote = compact(result.get("quote", ""))
    if any(compact(phrase) not in quote for phrase in unit.get("literal_conditions") or []):
        return False
    if unit.get("table") and not _table_holds(result, unit["table"]):
        return False
    if unit.get("numeric") and not _numeric_holds(result, unit["numeric"]):
        return False
    return True


def first_match_rank(results: Iterable[dict], units: list[dict], *, page_only: bool = False) -> int | None:
    ranks = [result["rank"] for result in results
             if any(unit_matches(result, unit, page_only=page_only) for unit in units)]
    return min(ranks, default=None)


def _within(rank: int | None, cutoff: int) -> bool:
    return rank is not None and rank <= cutoff


def summarize(case_ranks: list[int | None], unit_ranks: list[int | None]) -> dict:
    """case_ranks: first matching rank per answerable case; unit_ranks: per gold unit."""
    metrics: dict = {f"hit@{k}": [sum(_within(rank, k) for rank in case_ranks), len(case_ranks)] for k in HIT_LEVELS}
    metrics[f"unit_recall@{CUTOFF}"] = [sum(_within(rank, CUTOFF) for rank in unit_ranks), len(unit_ranks)]
    reciprocal = [1 / rank if _within(rank, CUTOFF) else 0.0 for rank in case_ranks]
    metrics[f"mrr@{CUTOFF}"] = sum(reciprocal) / len(reciprocal) if reciprocal else 0.0
    return metrics


def summarize_by_group(case_ranks: dict[str, int | None], unit_ranks: dict[str, list[int | None]],
                       groups: dict[str, str]) -> dict[str, dict]:
    """summarize() per group label (e.g. query_type). Every measured case must have a label."""
    missing = sorted(set(case_ranks) - set(groups))
    if missing:
        raise ValueError(f"cases without a group label: {missing}")
    labels = sorted({groups[case_id] for case_id in case_ranks})
    return {label: summarize([rank for case_id, rank in case_ranks.items() if groups[case_id] == label],
                             [rank for case_id, ranks in unit_ranks.items() if groups[case_id] == label
                              for rank in ranks])
            for label in labels}
