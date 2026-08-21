from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping

from ashare_review.calendar import last_completed_trading_day


def current_snapshot_matches_target(
    target_date: date,
    *,
    latest_completed: date | None = None,
) -> bool:
    """Whether a current-only provider can legitimately serve target_date."""
    completed = latest_completed or last_completed_trading_day()
    return target_date == completed


def _normalise_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"(?:概念|行业|板块|指数|Ⅱ|II)$", "", text)
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def filter_overlapping_industry_conflicts(
    rows: Iterable[Mapping[str, Any]],
    constituents_by_code: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    subset_threshold: float = 0.85,
    max_name_similarity: float = 0.55,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop suspicious smaller first-level industries duplicated by another node.

    Sina occasionally exposes a node whose label and constituent universe do
    not agree. First-level industries should not be near-complete subsets of an
    unrelated larger industry. The smaller conflicting row is removed rather
    than silently assigned a misleading label.
    """
    output = [dict(row) for row in rows]
    code_sets: dict[str, set[str]] = {}
    for row in output:
        board_code = str(row.get("board_code") or "")
        code_sets[board_code] = {
            str(item.get("code") or "").strip().zfill(6)
            for item in constituents_by_code.get(board_code, ())
            if item.get("code")
        }

    dropped_codes: set[str] = set()
    conflicts: list[dict[str, Any]] = []
    for smaller in output:
        small_code = str(smaller.get("board_code") or "")
        small_set = code_sets.get(small_code, set())
        if len(small_set) < 5:
            continue
        for larger in output:
            large_code = str(larger.get("board_code") or "")
            if small_code == large_code:
                continue
            large_set = code_sets.get(large_code, set())
            if len(large_set) < 5 or len(small_set) > len(large_set) * 0.80:
                continue
            overlap = len(small_set & large_set) / len(small_set)
            if overlap < subset_threshold:
                continue
            small_name = _normalise_name(smaller.get("board_name"))
            large_name = _normalise_name(larger.get("board_name"))
            similarity = SequenceMatcher(None, small_name, large_name).ratio()
            if similarity > max_name_similarity:
                continue
            dropped_codes.add(small_code)
            conflicts.append(
                {
                    "board_code": small_code,
                    "board_name": smaller.get("board_name"),
                    "duplicate_of": large_code,
                    "duplicate_name": larger.get("board_name"),
                    "subset_overlap": round(overlap, 4),
                    "name_similarity": round(similarity, 4),
                    "reason": "成份股高度重叠但行业名称不一致，未纳入排名",
                }
            )
            break

    kept = [row for row in output if str(row.get("board_code") or "") not in dropped_codes]
    return kept, conflicts
