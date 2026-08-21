from __future__ import annotations

from datetime import date

from ashare_review.sector_integrity import (
    current_snapshot_matches_target,
    filter_overlapping_industry_conflicts,
)


def test_current_only_snapshot_must_match_latest_completed_session() -> None:
    assert current_snapshot_matches_target(
        date(2026, 8, 21), latest_completed=date(2026, 8, 21)
    )
    assert not current_snapshot_matches_target(
        date(2026, 8, 20), latest_completed=date(2026, 8, 21)
    )


def test_mislabeled_near_subset_industry_is_removed() -> None:
    rows = [
        {
            "board_code": "hangye_ZB07",
            "board_name": "石油和天然气开采业",
            "board_type": "industry",
        },
        {
            "board_code": "hangye_ZB09",
            "board_name": "有色金属矿采选业",
            "board_type": "industry",
        },
        {
            "board_code": "hangye_ZC26",
            "board_name": "化学原料和化学制品制造业",
            "board_type": "industry",
        },
    ]
    mining_codes = [f"600{index:03d}" for index in range(1, 28)]
    constituents = {
        "hangye_ZB07": [{"code": code} for code in mining_codes[:16]],
        "hangye_ZB09": [{"code": code} for code in mining_codes],
        "hangye_ZC26": [{"code": f"000{index:03d}"} for index in range(1, 20)],
    }

    kept, conflicts = filter_overlapping_industry_conflicts(rows, constituents)

    assert [row["board_code"] for row in kept] == ["hangye_ZB09", "hangye_ZC26"]
    assert conflicts == [
        {
            "board_code": "hangye_ZB07",
            "board_name": "石油和天然气开采业",
            "duplicate_of": "hangye_ZB09",
            "duplicate_name": "有色金属矿采选业",
            "subset_overlap": 1.0,
            "name_similarity": 0.2857,
            "reason": "成份股高度重叠但行业名称不一致，未纳入排名",
        }
    ]
