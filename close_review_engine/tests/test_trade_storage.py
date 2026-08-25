from __future__ import annotations

import json
from pathlib import Path

import pytest

from ashare_review.storage import (
    TradeStateCorruptError,
    evaluate_saved_trades,
    load_trade_state,
    persist_trade_state,
)


def test_corrupt_active_plan_file_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "data/state/trade_plans.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(TradeStateCorruptError):
        load_trade_state(tmp_path)

    assert path.read_text(encoding="utf-8") == "{broken"


def test_persist_trade_state_deduplicates_outcomes_and_round_trips(tmp_path: Path) -> None:
    active = [{"plan_id": "p1", "lifecycle_status": "pending"}]
    outcome = {
        "plan_id": "old",
        "exit_date": "2026-08-25",
        "exit_reason": "stopped",
        "included_in_statistics": True,
        "return_pct": -5.0,
        "setup": "pullback",
        "market_regime": "neutral",
        "recommendation_type": "technical_only",
    }

    persist_trade_state(tmp_path, active, [outcome])
    persist_trade_state(tmp_path, active, [outcome])
    loaded_active, loaded_outcomes = load_trade_state(tmp_path)

    assert loaded_active == active
    assert loaded_outcomes == [outcome]
    outcome_lines = (tmp_path / "data/state/trade_outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(outcome_lines) == 1


def test_evaluate_saved_trades_reads_outcomes_without_mutating_state(tmp_path: Path) -> None:
    active = [{"plan_id": "p1", "lifecycle_status": "pending"}]
    outcome = {
        "plan_id": "old",
        "exit_date": "2026-08-25",
        "exit_reason": "target2",
        "included_in_statistics": True,
        "return_pct": 8.0,
        "setup": "breakout",
        "market_regime": "risk_on",
        "recommendation_type": "comprehensive",
    }
    persist_trade_state(tmp_path, active, [outcome])
    plan_path = tmp_path / "data/state/trade_plans.json"
    before = plan_path.read_bytes()

    stats = evaluate_saved_trades(tmp_path)

    assert stats["sample_count"] == 1
    assert plan_path.read_bytes() == before
    assert json.loads(plan_path.read_text(encoding="utf-8"))[0]["plan_id"] == "p1"
