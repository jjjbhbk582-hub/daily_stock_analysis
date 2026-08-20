from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ashare_review.indicators import finite

MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


@dataclass(frozen=True, slots=True)
class FocusConcept:
    label: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectorMonitorConfig:
    max_price: float
    min_amount: float
    max_detailed_boards: int
    shortlist_per_board: int
    max_dynamic_stocks: int
    history_candidates_per_type: int
    focus_concepts: tuple[FocusConcept, ...]


def load_sector_monitor(path: str | Path) -> SectorMonitorConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    concepts = tuple(
        FocusConcept(
            label=str(item["label"]),
            aliases=tuple(dict.fromkeys([str(item["label"]), *(str(value) for value in item.get("aliases", []))])),
        )
        for item in payload.get("focus_concepts", [])
    )
    if not concepts:
        raise ValueError("sector monitor config must contain focus_concepts")
    config = SectorMonitorConfig(
        max_price=float(payload.get("max_price", 100.0)),
        min_amount=float(payload.get("min_amount", 300_000_000)),
        max_detailed_boards=int(payload.get("max_detailed_boards", 7)),
        shortlist_per_board=int(payload.get("shortlist_per_board", 8)),
        max_dynamic_stocks=int(payload.get("max_dynamic_stocks", 48)),
        history_candidates_per_type=int(payload.get("history_candidates_per_type", 15)),
        focus_concepts=concepts,
    )
    if config.max_price > 100.0:
        raise ValueError("max_price must not exceed 100.00")
    if config.min_amount < 300_000_000:
        raise ValueError("min_amount must not be below CNY 300 million")
    if not 1 <= config.max_detailed_boards <= 7:
        raise ValueError("max_detailed_boards must be between 1 and 7")
    return config


def is_eligible_main_board(row: Mapping[str, Any], config: SectorMonitorConfig) -> bool:
    code = str(row.get("code") or "").strip().zfill(6)
    name = str(row.get("name") or "").strip()
    upper_name = name.upper()
    close = finite(row.get("close"))
    amount = finite(row.get("amount"), 0.0) or 0.0
    volume = finite(row.get("volume"), 0.0) or 0.0
    high = finite(row.get("high"))
    low = finite(row.get("low"))
    pct_change = abs(finite(row.get("pct_change"), 0.0) or 0.0)
    prefix_ok = code.startswith(MAIN_BOARD_PREFIXES)
    risk_name = "ST" in upper_name or "退" in name
    one_price_limit = (
        high is not None
        and low is not None
        and abs(high - low) < 1e-8
        and pct_change >= 9.5
    )
    return bool(
        prefix_ok
        and close is not None
        and 0 < close <= config.max_price
        and amount >= config.min_amount
        and volume > 0
        and not risk_name
        and not one_price_limit
    )
