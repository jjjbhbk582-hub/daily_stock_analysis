from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_review.config import load_universe
from ashare_review.engine import FixtureDataSource, run_review
from ashare_review.report import render_report
from ashare_review.storage import load_previous_snapshot, should_preserve, write_outputs

TARGET = date(2026, 8, 20)
TZ = ZoneInfo("Asia/Shanghai")


def build_snapshot(tmp_path: Path):
    stocks = load_universe("config/universe.yml")
    source = FixtureDataSource.from_path("config/review_fixture.yml")
    result = run_review(
        stocks,
        source,
        target_date=TARGET,
        generated_at=datetime(2026, 8, 20, 15, 30, tzinfo=TZ),
        max_workers=4,
    )
    assert result.snapshot is not None
    return result.snapshot


def test_fixture_pipeline_outputs_17_rows_and_top5(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    assert snapshot["status"] == "success"
    assert snapshot["valid_count"] == 17
    assert len(snapshot["stocks"]) == 17
    assert len(snapshot["top5"]) == 5
    assert [row["rank"] for row in snapshot["stocks"]] == list(range(1, 18))
    assert all(row["data_date"] == TARGET.isoformat() for row in snapshot["stocks"])
    assert all(row["rating"] in {"S", "A+", "A", "A-", "B+", "B", "C", "D"} for row in snapshot["stocks"])


def test_fixture_pipeline_contains_sector_rankings_and_2plus2(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    assert snapshot["schema_version"] == 2
    sectors = snapshot["sectors"]
    assert sectors["industry_ranking"]
    assert sectors["concept_ranking"]
    assert len(sectors["focus_concepts"]) >= 12
    assert len(sectors["top_boards"]) == 5
    assert len(sectors["detailed_boards"]) <= 7
    for board in sectors["detailed_boards"]:
        assert set(board["picks"]) == {
            "capacity_leader",
            "momentum_leader",
            "pullback_potential",
            "breakout_potential",
        }
        codes = [pick["code"] for pick in board["picks"].values() if pick.get("code")]
        assert len(codes) == len(set(codes))
        assert all(float(pick["close"]) <= 100 for pick in board["picks"].values() if pick.get("code"))


def test_report_has_sector_panorama_2plus2_and_fixed_pool_sections(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    report = render_report(snapshot)
    for heading in (
        "第一部分：市场环境",
        "第二部分：行业板块完整排名",
        "第三部分：重点概念板块",
        "第四部分：强势、上升与退潮板块",
        "第五部分：重点板块2+2",
        "第六部分：17只固定股票完整排名",
        "第七部分：固定池Top5重点分析",
        "第八部分：动态候选买点",
        "第九部分：与上一次排名对比",
        "第十部分：最终操作结论",
    ):
        assert heading in report
    assert "资金容量龙头" in report
    assert "弹性龙头" in report
    assert "缩量回踩潜力" in report
    assert "放量突破潜力" in report
    assert report.count("最理想回踩买入区间") >= 5
    assert "不承诺收益" in report


def test_storage_writes_all_contract_outputs_and_sector_history(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    report = render_report(snapshot)
    paths = write_outputs(tmp_path, snapshot, report)
    assert paths.snapshot.is_file()
    assert paths.ranking.is_file()
    assert paths.report.is_file()
    assert paths.latest.is_file()
    previous = load_previous_snapshot(tmp_path, before_date="2026-08-21")
    assert previous is not None
    assert previous["target_date"] == TARGET.isoformat()
    history_text = paths.history.read_text(encoding="utf-8")
    assert '"sectors"' in history_text


def test_better_same_day_run_is_preserved(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    worse = dict(snapshot)
    worse["valid_count"] = 12
    assert should_preserve(snapshot, worse)
    assert not should_preserve(worse, snapshot)
