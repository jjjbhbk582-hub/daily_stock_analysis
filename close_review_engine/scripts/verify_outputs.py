from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


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
    if len(snapshot.get("stocks") or []) != 17 or len(rows) != 17:
        raise SystemExit("output must contain exactly 17 stocks")
    if len(snapshot.get("top5") or []) != 5:
        raise SystemExit("output must contain exactly five Top5 codes")
    if len({row.get("code") for row in snapshot["stocks"]}) != 17:
        raise SystemExit("duplicate or missing stock codes")
    for heading in (
        "第一部分：市场环境",
        "第二部分：17只股票完整排名",
        "第三部分：Top5重点分析",
        "第四部分：和上一次排名对比",
        "第五部分：买点变化提醒",
        "最终操作结论",
    ):
        if heading not in report:
            raise SystemExit(f"report missing section: {heading}")
    if report.count("### ") < 6:
        raise SystemExit("report missing Top5 detail blocks")
    print(
        json.dumps(
            {
                "target_date": target_date,
                "status": snapshot.get("status"),
                "valid_count": snapshot.get("valid_count"),
                "ranking_rows": len(rows),
                "top5": snapshot.get("top5"),
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
