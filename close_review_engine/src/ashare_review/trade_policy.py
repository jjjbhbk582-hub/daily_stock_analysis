from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TradePolicy:
    version: str = "v1"
    min_technical_score: float = 70.0
    watch_technical_score: float = 65.0
    min_rr1: float = 1.8
    breakout_volume_ratio: float = 1.3
    risk_budget_pct: float = 0.5
    max_holding_sessions: int = 5
    max_sector_weight_pct: float = 25.0


DEFAULT_POLICY = TradePolicy()
