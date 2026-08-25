from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ALLOWED_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
ROLE_KEYS = {
    "capacity_leader",
    "momentum_leader",
    "pullback_potential",
    "breakout_potential",
}


def verify(root: Path, target_date: str) -> None:
    snapshot_path = root / "data" / "processed" / target_date / "snapshot.json"
    ranking_path = root / "data" / "processed" / target_date / "ranking.csv"
    report_path = root / "reports" / f"{target_date}.md"
    latest_path = root / "data" / "state" / "latest.json"
    for path in (snapshot_path, ranking_path, report_path, latest_path):
        if not path.is_file():
            raise SystemExit(f"missing required output: {path}")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(ranking_path.open(encoding="utf-8-sig")))
    report = report_path.read_text(encoding="utf-8")
    if snapshot.get("target_date") != target_date or latest.get("target_date") != target_date:
        raise SystemExit("target date mismatch")
    if int(snapshot.get("schema_version") or 0) != 2:
        raise SystemExit("snapshot schema_version must be 2")
    universe_count = int(snapshot.get("universe_count") or 0)
    if universe_count <= 0:
        raise SystemExit("snapshot universe_count must be positive")
    if len(snapshot.get("stocks") or []) != universe_count or len(rows) != universe_count:
        raise SystemExit("output fixed-stock rows must match snapshot universe_count")
    if len(snapshot.get("top5") or []) != 5:
        raise SystemExit("output must contain exactly five fixed-pool Top5 codes")
    if len({row.get("code") for row in snapshot["stocks"]}) != universe_count:
        raise SystemExit("duplicate or missing fixed stock codes")
    decision = snapshot.get("trade_decision") or {}
    if decision.get("status") not in {"ready", "empty", "unavailable"}:
        raise SystemExit("snapshot trade_decision status is invalid")
    for key in (
        "executable",
        "ready_next_session",
        "waiting_trigger",
        "watch_only",
        "rejected",
    ):
        if key not in decision:
            raise SystemExit(f"trade_decision missing key: {key}")
    if "previous_trade_review" not in snapshot or "trade_statistics" not in snapshot:
        raise SystemExit("snapshot missing trade tracking fields")

    sectors = snapshot.get("sectors") or {}
    for key in (
        "industry_ranking",
        "concept_ranking",
        "focus_concepts",
        "top_boards",
        "rising_boards",
        "weak_boards",
        "detailed_boards",
        "dynamic_candidates",
        "comparison",
        "source_status",
    ):
        if key not in sectors:
            raise SystemExit(f"sectors missing key: {key}")
    if not sectors["industry_ranking"] or not sectors["concept_ranking"]:
        raise SystemExit("fixture must produce non-empty industry and concept rankings")
    if len(sectors["top_boards"]) != 5:
        raise SystemExit("sector output must contain five top boards")
    if len(sectors["detailed_boards"]) > 7:
        raise SystemExit("detailed boards must not exceed seven")
    if len(sectors["focus_concepts"]) < 12:
        raise SystemExit("focus concepts are incomplete")
    for board in sectors["detailed_boards"]:
        picks = board.get("picks") or {}
        if set(picks) != ROLE_KEYS:
            raise SystemExit(f"board roles incomplete: {board.get('board_name')}")
        chosen = []
        for item in picks.values():
            code = item.get("code")
            if not code:
                continue
            code = str(code)
            chosen.append(code)
            if not code.startswith(ALLOWED_PREFIXES):
                raise SystemExit(f"dynamic pick is not main-board A-share: {code}")
            close = float(item.get("close"))
            if not 0 < close <= 100:
                raise SystemExit(f"dynamic pick violates CNY 100 cap: {code} {close}")
            name = str(item.get("name") or "")
            if "ST" in name.upper() or "退" in name:
                raise SystemExit(f"dynamic pick has risk name: {code} {name}")
        if len(chosen) != len(set(chosen)):
            raise SystemExit(f"duplicate role stock in board: {board.get('board_name')}")

    for heading in (
        "第一部分：市场环境",
        "第二部分：行业板块完整排名",
        "第三部分：重点概念板块",
        "第四部分：强势、上升与退潮板块",
        "第五部分：重点板块2+2",
        f"第六部分：{universe_count}只固定股票完整排名",
        "第七部分：固定池Top5重点分析",
        "第八部分：动态候选买点",
        "第九部分：与上一次排名对比",
        "第十部分：推荐交易计划",
        "第十一部分：最终操作结论",
    ):
        if heading not in report:
            raise SystemExit(f"report missing section: {heading}")
    for label in ("资金容量龙头", "弹性龙头", "缩量回踩潜力", "放量突破潜力"):
        if label not in report:
            raise SystemExit(f"report missing 2+2 role: {label}")
    if report.count("最理想回踩买入区间") < 5:
        raise SystemExit("report missing fixed Top5 level details")
    for label in (
        "今日可执行",
        "等待触发",
        "回踩计划明细",
        "突破计划明细",
        "累计统计与样本置信度",
    ):
        if label not in report:
            raise SystemExit(f"report missing trade decision contract: {label}")
    print(
        json.dumps(
            {
                "target_date": target_date,
                "status": snapshot.get("status"),
                "valid_count": snapshot.get("valid_count"),
                "ranking_rows": len(rows),
                "top5": snapshot.get("top5"),
                "industry_boards": len(sectors["industry_ranking"]),
                "concept_boards": len(sectors["concept_ranking"]),
                "detailed_boards": len(sectors["detailed_boards"]),
                "dynamic_candidates": len(sectors["dynamic_candidates"]),
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_outputs.py OUTPUT_ROOT YYYY-MM-DD", file=sys.stderr)
        return 2
    verify(Path(sys.argv[1]), sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
