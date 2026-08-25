from __future__ import annotations

import pytest

from ashare_review.trade_plans import build_trade_regime, model_weight_pct


def risk_on_market():
    return {
        "indices": [{"pct_change": 1.2}, {"pct_change": 1.0}, {"pct_change": 0.8}],
        "breadth": {"up": 3400, "down": 900, "median_pct": 0.9},
        "industry_table": [
            {"pct_change": 1.0},
            {"pct_change": 0.8},
            {"pct_change": 0.2},
            {"pct_change": -0.1},
        ],
    }


def neutral_market():
    return {
        "indices": [{"pct_change": 0.0}, {"pct_change": 0.0}, {"pct_change": 0.0}],
        "breadth": {"up": 2000, "down": 2000, "median_pct": 0.0},
        "industry_table": [{"pct_change": 0.1}, {"pct_change": -0.1}],
    }


def risk_off_market():
    return {
        "indices": [{"pct_change": -1.2}, {"pct_change": -1.0}, {"pct_change": -0.8}],
        "breadth": {"up": 800, "down": 3500, "median_pct": -1.0},
        "industry_table": [
            {"pct_change": -1.0},
            {"pct_change": -0.8},
            {"pct_change": -0.2},
            {"pct_change": 0.1},
        ],
    }


@pytest.mark.parametrize(
    ("market", "label", "cap"),
    [
        (risk_on_market(), "risk_on", 70.0),
        (neutral_market(), "neutral", 50.0),
        (risk_off_market(), "risk_off", 30.0),
    ],
)
def test_market_regime_sets_portfolio_cap(market, label, cap) -> None:
    regime = build_trade_regime(market)

    assert regime["label"] == label
    assert regime["max_total_weight_pct"] == cap
    assert 0 <= regime["score"] <= 100
    assert len(regime["evidence"]) == 4


def test_missing_fundamentals_cap_position_even_with_tight_stop() -> None:
    assert model_weight_pct(10.0, 9.8, "missing", 70.0, 25.0) == 7.5


def test_verified_position_uses_half_percent_risk_budget() -> None:
    assert model_weight_pct(10.0, 9.5, "verified", 70.0, 25.0) == 10.0


def test_invalid_stop_distance_produces_zero_weight() -> None:
    assert model_weight_pct(10.0, 10.0, "verified", 70.0, 25.0) == 0.0
