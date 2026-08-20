from __future__ import annotations

from ashare_review.sector_candidates import assign_roles, shortlist_constituents
from ashare_review.sector_config import load_sector_monitor


def _constituent(code: str, name: str, **overrides):
    row = {
        "code": code,
        "name": name,
        "close": 50.0,
        "pct_change": 2.0,
        "amount": 1_000_000_000,
        "volume": 20_000_000,
        "turnover_rate": 4.0,
        "high": 51.0,
        "low": 49.0,
        "open": 49.5,
        "previous_close": 49.0,
        "market_cap": 50_000_000_000,
        "float_market_cap": 40_000_000_000,
    }
    row.update(overrides)
    return row


def _analyzed(code: str, name: str, **overrides):
    row = {
        "code": code,
        "name": name,
        "close": 50.0,
        "pct_change": 2.0,
        "data_valid": True,
        "data_confidence": "high",
        "daily_trend": "多头",
        "weekly_trend": "多头",
        "trend_60m": "偏多震荡",
        "patterns": [],
        "levels": {
            "status": "ready",
            "pullback_low": 48.5,
            "pullback_high": 50.5,
            "breakout_trigger": 51.5,
            "no_chase_above": 55.0,
            "invalidation": 46.0,
            "target_1": 56.0,
            "target_2": 60.0,
            "risk_reward_1": 1.6,
            "risk_reward_2": 2.5,
        },
        "metrics": {"amount": 1_000_000_000, "turnover_rate": 4.0, "rel_volume_20": 0.9, "rsi_14": 58.0},
        "candidate_snapshot": _constituent(code, name),
    }
    row.update(overrides)
    return row


def test_shortlist_applies_hard_filter_and_limit() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    rows = [
        _constituent("600001", "容量股", amount=8_000_000_000),
        _constituent("002156", "弹性股", amount=6_000_000_000, pct_change=6.0),
        _constituent("300308", "创业板股", amount=10_000_000_000),
        _constituent("600002", "高价股", close=101.0),
        _constituent("600003", "ST风险"),
    ]
    shortlist = shortlist_constituents(rows, config)
    assert [row["code"] for row in shortlist] == ["600001", "002156"]
    assert len(shortlist) <= config.shortlist_per_board


def test_assign_roles_never_reuses_stock_and_does_not_force_four() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    rows = [
        _analyzed(
            "600001",
            "容量股",
            candidate_snapshot=_constituent("600001", "容量股", amount=12_000_000_000, market_cap=150_000_000_000),
        ),
        _analyzed(
            "002156",
            "弹性股",
            pct_change=7.0,
            patterns=["放量突破"],
            metrics={"amount": 7_000_000_000, "turnover_rate": 9.0, "rel_volume_20": 1.5, "rsi_14": 67.0},
            candidate_snapshot=_constituent("002156", "弹性股", amount=7_000_000_000, pct_change=7.0, turnover_rate=9.0),
        ),
        _analyzed(
            "603001",
            "回踩股",
            patterns=["缩量回踩"],
            metrics={"amount": 900_000_000, "turnover_rate": 2.0, "rel_volume_20": 0.65, "rsi_14": 52.0},
            candidate_snapshot=_constituent("603001", "回踩股", amount=900_000_000, pct_change=0.5, turnover_rate=2.0),
        ),
    ]
    picks = assign_roles(
        {"board_code": "BK1", "board_name": "测试板块", "board_type": "industry"},
        rows,
        config,
    )
    assert set(picks) == {
        "capacity_leader",
        "momentum_leader",
        "pullback_potential",
        "breakout_potential",
    }
    chosen = [item["code"] for item in picks.values() if item.get("code")]
    assert len(chosen) == len(set(chosen))
    assert len(chosen) == 3
    assert any(item.get("status") == "no_qualified_stock" for item in picks.values())
    assert all(float(item["close"]) <= 100 for item in picks.values() if item.get("code"))
