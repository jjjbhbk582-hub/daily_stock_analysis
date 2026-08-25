from __future__ import annotations

from pathlib import Path

from ashare_review.cli import main
from ashare_review.storage import persist_trade_state


def test_evaluate_trades_prints_saved_statistics_without_mutating_plans(
    tmp_path: Path,
    capsys,
) -> None:
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
    path = tmp_path / "data/state/trade_plans.json"
    before = path.read_bytes()

    assert main(["evaluate-trades", "--output-root", str(tmp_path)]) == 0

    assert '"sample_count": 1' in capsys.readouterr().out
    assert path.read_bytes() == before
