from __future__ import annotations

import subprocess
import sys
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


def test_fixture_pipeline_outputs_all_59_monitoring_rows_and_top5(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    assert snapshot["status"] == "success"
    assert snapshot["valid_count"] == 59
    assert snapshot["universe_count"] == 59
    assert len(snapshot["stocks"]) == 59
    assert len(snapshot["top5"]) == 5
    assert [row["rank"] for row in snapshot["stocks"]] == list(range(1, 60))
    assert all(row["data_date"] == TARGET.isoformat() for row in snapshot["stocks"])
    assert all(row["rating"] in {"S", "A+", "A", "A-", "B+", "B", "C", "D"} for row in snapshot["stocks"])
    assert all("technical_trade_score" in row for row in snapshot["stocks"])
    assert all("fundamental_status" in row for row in snapshot["stocks"])


def test_fixture_pipeline_adds_a_next_session_trade_decision_without_replacing_rankings(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(tmp_path)

    decision = snapshot["trade_decision"]
    assert decision["status"] in {"ready", "empty"}
    assert decision["target_date"] == "2026-08-20"
    assert decision["valid_for"] == "2026-08-21"
    assert decision["market_regime"]["label"] in {"risk_on", "neutral", "risk_off"}
    assert decision["executable"] == decision["ready_next_session"]
    assert len(snapshot["top5"]) == 5


def test_run_review_evaluates_saved_plans_before_generating_new_ones(tmp_path: Path) -> None:
    stocks = load_universe("config/universe.yml")
    source = FixtureDataSource.from_path("config/review_fixture.yml")
    active = [
        {
            "plan_id": "2026-08-19:601138:pullback:v1",
            "code": "601138",
            "name": "工业富联",
            "industry": "电子元件",
            "setup": "pullback",
            "recommendation_type": "technical_only",
            "fundamental_status": "missing",
            "market_regime": "neutral",
            "lifecycle_status": "pending",
            "valid_for": "2026-08-20",
            "expires_after": "2026-08-20",
            "entry": {"low": 0.5, "high": 999.0, "reference": 1.0},
            "trigger": {"kind": "pullback_reclaim", "confirmation_level": 1.0},
            "stop": 0.1,
            "target_1": 1000.0,
            "target_2": 2000.0,
            "no_chase_above": 5000.0,
            "max_holding_sessions": 5,
        }
    ]

    result = run_review(
        stocks,
        source,
        target_date=TARGET,
        generated_at=datetime(2026, 8, 20, 15, 30, tzinfo=TZ),
        active_plans=active,
        outcomes=[],
        max_workers=4,
    )

    assert result.snapshot is not None
    assert result.snapshot["previous_trade_review"][0]["lifecycle_status"] == "triggered"
    assert result.snapshot["trade_statistics"]["sample_count"] == 0
    assert any(plan["plan_id"] == active[0]["plan_id"] for plan in result.active_plans)
    generated = result.snapshot["trade_decision"]["ready_next_session"] + result.snapshot["trade_decision"]["waiting_trigger"]
    assert all(plan["market_regime"] in {"risk_on", "neutral", "risk_off"} for plan in generated)


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
        "第六部分：59只固定股票完整排名",
        "第七部分：固定池Top5重点分析",
        "第八部分：动态候选买点",
        "第九部分：与上一次排名对比",
        "第十部分：推荐交易计划",
        "第十一部分：最终操作结论",
    ):
        assert heading in report
    assert "资金容量龙头" in report
    assert "弹性龙头" in report
    assert "缩量回踩潜力" in report
    assert "放量突破潜力" in report
    assert report.count("最理想回踩买入区间") >= 5
    assert "今日可执行" in report
    assert "等待触发" in report
    assert "止损" in report
    assert "目标1/2" in report
    assert "禁止追高" in report
    assert "模型仓位上限" in report
    assert "推荐依据与缺失字段" in report
    assert "绝对门槛：" in report
    assert "昨日计划验收" in report
    assert "累计统计与样本置信度" in report
    assert "统计置信度不足" in report
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
    assert b"\r\n" not in paths.ranking.read_bytes()


def test_verify_outputs_script_accepts_the_current_eleven_section_contract(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    paths = write_outputs(tmp_path, snapshot, render_report(snapshot))
    script = Path(__file__).parents[1] / "scripts" / "verify_outputs.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path), TARGET.isoformat()],
        capture_output=True,
        text=True,
        check=False,
    )

    assert paths.report.is_file()
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_better_same_day_run_is_preserved(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    worse = dict(snapshot)
    worse["valid_count"] = 12
    assert should_preserve(snapshot, worse)
    assert not should_preserve(worse, snapshot)
