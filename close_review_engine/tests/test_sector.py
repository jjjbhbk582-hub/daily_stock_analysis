from __future__ import annotations

import pandas as pd

from ashare_review.sector import (
    assign_sector_roles,
    filter_eligible_candidates,
    rank_sector_rows,
    select_key_sectors,
)


def _spot_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "code": "600001",
                "name": "容量龙头",
                "close": 88.0,
                "pct_change": 3.2,
                "amount": 8_000_000_000,
                "turnover_rate": 5.0,
                "open": 85.0,
                "high": 89.0,
                "low": 84.0,
            },
            {
                "code": "000001",
                "name": "深市候选",
                "close": 99.0,
                "pct_change": 2.1,
                "amount": 1_200_000_000,
                "turnover_rate": 4.0,
                "open": 97.0,
                "high": 99.5,
                "low": 96.5,
            },
            {
                "code": "300001",
                "name": "创业板排除",
                "close": 35.0,
                "pct_change": 6.0,
                "amount": 3_000_000_000,
                "turnover_rate": 12.0,
                "open": 32.0,
                "high": 36.0,
                "low": 31.5,
            },
            {
                "code": "688001",
                "name": "科创板排除",
                "close": 45.0,
                "pct_change": 5.0,
                "amount": 2_000_000_000,
                "turnover_rate": 8.0,
                "open": 43.0,
                "high": 46.0,
                "low": 42.5,
            },
            {
                "code": "600002",
                "name": "超过百元",
                "close": 100.01,
                "pct_change": 2.0,
                "amount": 2_000_000_000,
                "turnover_rate": 4.0,
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
            },
            {
                "code": "600003",
                "name": "*ST风险",
                "close": 8.0,
                "pct_change": 4.8,
                "amount": 900_000_000,
                "turnover_rate": 7.0,
                "open": 7.7,
                "high": 8.0,
                "low": 7.6,
            },
            {
                "code": "600004",
                "name": "一字涨停",
                "close": 20.0,
                "pct_change": 10.0,
                "amount": 500_000_000,
                "turnover_rate": 1.0,
                "open": 20.0,
                "high": 20.0,
                "low": 20.0,
            },
            {
                "code": "600005",
                "name": "流动性不足",
                "close": 15.0,
                "pct_change": 1.0,
                "amount": 80_000_000,
                "turnover_rate": 0.5,
                "open": 14.8,
                "high": 15.2,
                "low": 14.7,
            },
        ]
    )


def test_candidate_filter_enforces_main_board_price_and_risk_rules() -> None:
    eligible = filter_eligible_candidates(_spot_rows())
    assert eligible["code"].tolist() == ["600001", "000001"]
    assert eligible["close"].max() <= 100


def test_sector_ranking_uses_six_component_100_point_model() -> None:
    rows = [
        {
            "label": "hangye_a",
            "sector_name": "通信设备",
            "pct_change": 3.2,
            "amount": 90_000_000_000,
            "count": 80,
            "leader_pct_change": 9.8,
        },
        {
            "label": "hangye_b",
            "sector_name": "半导体",
            "pct_change": 1.5,
            "amount": 150_000_000_000,
            "count": 180,
            "leader_pct_change": 6.2,
        },
        {
            "label": "hangye_c",
            "sector_name": "煤炭",
            "pct_change": -1.1,
            "amount": 20_000_000_000,
            "count": 35,
            "leader_pct_change": 1.0,
        },
    ]
    ranked = rank_sector_rows(rows, kind="industry", market_median_pct=0.3)
    assert [row["rank"] for row in ranked] == [1, 2, 3]
    assert ranked[0]["sector_name"] == "通信设备"
    assert 0 <= ranked[0]["score"] <= 100
    assert set(ranked[0]["score_components"]) == {
        "relative_strength",
        "persistence",
        "liquidity",
        "breadth",
        "leadership",
        "catalyst_risk",
    }
    assert ranked[0]["persistence_status"] == "unverified"


def test_key_sector_selection_adds_rank_risers_without_duplicates() -> None:
    industries = [
        {"sector_id": "industry:a", "rank": 1, "score": 82, "sector_name": "A"},
        {"sector_id": "industry:b", "rank": 2, "score": 78, "sector_name": "B"},
        {"sector_id": "industry:c", "rank": 3, "score": 75, "sector_name": "C"},
    ]
    concepts = [
        {"sector_id": "concept:x", "rank": 1, "score": 80, "sector_name": "X"},
        {"sector_id": "concept:y", "rank": 2, "score": 74, "sector_name": "Y"},
    ]
    previous = {
        "sector_analysis": {
            "industry_ranking": [
                {"sector_id": "industry:a", "rank": 1},
                {"sector_id": "industry:b", "rank": 2},
                {"sector_id": "industry:c", "rank": 9},
            ],
            "concept_ranking": [
                {"sector_id": "concept:x", "rank": 1},
                {"sector_id": "concept:y", "rank": 8},
            ],
        }
    }
    selected = select_key_sectors(
        industries,
        concepts,
        previous_snapshot=previous,
        top_n=2,
        max_risers=2,
    )
    ids = [row["sector_id"] for row in selected]
    assert ids[:2] == ["industry:a", "concept:x"]
    assert "industry:c" in ids
    assert "concept:y" in ids
    assert len(ids) == len(set(ids))


def _candidate(
    code: str,
    *,
    amount: float,
    pct_change: float,
    turnover_rate: float,
    rel_volume: float,
    patterns: list[str],
    breakout_gap: float,
) -> dict:
    close = 50.0
    return {
        "code": code,
        "name": code,
        "close": close,
        "pct_change": pct_change,
        "amount": amount,
        "turnover_rate": turnover_rate,
        "relative_volume_20": rel_volume,
        "daily_trend": "偏多震荡",
        "weekly_trend": "多头",
        "trend_60m": "偏多震荡",
        "patterns": patterns,
        "levels": {
            "status": "ready",
            "pullback_low": 48.0,
            "pullback_high": 51.0,
            "breakout_trigger": close * (1 + breakout_gap),
            "invalidation": 45.0,
            "target_1": 58.0,
            "target_2": 64.0,
        },
    }


def test_2plus2_roles_are_unique_and_do_not_force_fill() -> None:
    candidates = [
        _candidate(
            "600001",
            amount=9_000_000_000,
            pct_change=2.0,
            turnover_rate=4.0,
            rel_volume=1.1,
            patterns=[],
            breakout_gap=0.08,
        ),
        _candidate(
            "600002",
            amount=4_000_000_000,
            pct_change=7.0,
            turnover_rate=12.0,
            rel_volume=1.8,
            patterns=[],
            breakout_gap=0.06,
        ),
        _candidate(
            "600003",
            amount=2_000_000_000,
            pct_change=0.8,
            turnover_rate=3.0,
            rel_volume=0.7,
            patterns=["缩量回踩"],
            breakout_gap=0.07,
        ),
        _candidate(
            "600004",
            amount=3_000_000_000,
            pct_change=3.5,
            turnover_rate=5.0,
            rel_volume=1.4,
            patterns=["放量突破"],
            breakout_gap=0.018,
        ),
    ]
    roles = assign_sector_roles(candidates)
    codes = [item["code"] for item in roles.values() if item]
    assert roles["capacity_leader"]["code"] == "600001"
    assert roles["elasticity_leader"]["code"] == "600002"
    assert roles["pullback_candidate"]["code"] == "600003"
    assert roles["breakout_candidate"]["code"] == "600004"
    assert len(codes) == len(set(codes)) == 4

    partial = assign_sector_roles(candidates[:2])
    assert sum(item is not None for item in partial.values()) == 2
