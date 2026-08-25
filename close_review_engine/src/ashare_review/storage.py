from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_review.trade_tracking import calculate_trade_statistics


class TradeStateCorruptError(ValueError):
    pass


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TradeStateCorruptError(f"交易计划状态文件损坏：{path}") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise TradeStateCorruptError(f"交易计划状态格式错误：{path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TradeStateCorruptError(f"交易结果状态文件不可读：{path}") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TradeStateCorruptError(f"交易结果状态文件损坏：{path}") from exc
        if not isinstance(item, dict):
            raise TradeStateCorruptError(f"交易结果状态格式错误：{path}")
        rows.append(item)
    return rows


def load_trade_state(root: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state_dir = Path(root) / "data" / "state"
    plans_path = state_dir / "trade_plans.json"
    outcomes_path = state_dir / "trade_outcomes.jsonl"
    plans = _read_json_list(plans_path) if plans_path.is_file() else []
    outcomes = _read_jsonl(outcomes_path) if outcomes_path.is_file() else []
    return plans, outcomes


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def persist_trade_state(
    root: str | Path,
    active_plans: list[dict[str, Any]],
    new_outcomes: list[dict[str, Any]],
) -> None:
    _, existing_outcomes = load_trade_state(root)
    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in [*existing_outcomes, *new_outcomes]:
        key = (
            str(item.get("plan_id") or ""),
            str(item.get("exit_date") or ""),
            str(item.get("exit_reason") or ""),
        )
        deduplicated[key] = item
    state_dir = Path(root) / "data" / "state"
    plans_text = json.dumps(active_plans, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    outcomes_text = "".join(
        json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n"
        for item in deduplicated.values()
    )
    _atomic_write(state_dir / "trade_plans.json", plans_text)
    _atomic_write(state_dir / "trade_outcomes.jsonl", outcomes_text)


def evaluate_saved_trades(root: str | Path) -> dict[str, Any]:
    _, outcomes = load_trade_state(root)
    return calculate_trade_statistics(outcomes)


@dataclass(frozen=True, slots=True)
class OutputPaths:
    report: Path
    snapshot: Path
    ranking: Path
    latest: Path
    history: Path
    preserved_existing: bool = False


def load_previous_snapshot(root: str | Path, *, before_date: str) -> dict[str, Any] | None:
    base = Path(root) / "data" / "processed"
    if not base.exists():
        return None
    candidates = sorted(
        [path for path in base.glob("*/snapshot.json") if path.parent.name < before_date],
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("stocks"):
            return payload
    return None


def load_same_day_snapshot(root: str | Path, *, target_date: str) -> dict[str, Any] | None:
    path = Path(root) / "data" / "processed" / target_date / "snapshot.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sector_completeness(snapshot: dict[str, Any]) -> tuple[int, int]:
    sectors = snapshot.get("sectors") or {}
    historical = sum(
        1
        for key in ("industry_ranking", "concept_ranking")
        for row in sectors.get(key, [])
        if row.get("confidence") == "high"
    )
    picks = sum(
        1
        for board in sectors.get("detailed_boards", [])
        for item in (board.get("picks") or {}).values()
        if item.get("status") == "ready" and item.get("code")
    )
    return historical, picks


def should_preserve(existing: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not existing:
        return False
    old_valid = int(existing.get("valid_count") or 0)
    new_valid = int(current.get("valid_count") or 0)
    if old_valid > new_valid:
        return True
    if old_valid < new_valid:
        return False
    old_high = sum(1 for row in existing.get("stocks", []) if row.get("data_confidence") == "high")
    new_high = sum(1 for row in current.get("stocks", []) if row.get("data_confidence") == "high")
    if old_high > new_high:
        return True
    if old_high < new_high:
        return False
    return _sector_completeness(existing) > _sector_completeness(current)


def _compact_sectors(snapshot: dict[str, Any]) -> dict[str, Any]:
    sectors = snapshot.get("sectors") or {}
    rankings: dict[str, list[dict[str, Any]]] = {}
    for key in ("industry_ranking", "concept_ranking"):
        rankings[key] = [
            {
                "rank": row.get("rank"),
                "board_type": row.get("board_type"),
                "board_code": row.get("board_code"),
                "board_name": row.get("board_name"),
                "score": row.get("score"),
                "pct_change": row.get("pct_change"),
                "confidence": row.get("confidence"),
            }
            for row in sectors.get(key, [])
        ]
    return {
        **rankings,
        "top_boards": [
            {
                "board_type": row.get("board_type"),
                "board_code": row.get("board_code"),
                "board_name": row.get("board_name"),
                "rank": row.get("rank"),
                "score": row.get("score"),
            }
            for row in sectors.get("top_boards", [])
        ],
        "focus_concepts": [
            {
                "focus_label": row.get("focus_label"),
                "board_code": row.get("board_code"),
                "rank": row.get("rank"),
                "score": row.get("score"),
                "pct_change": row.get("pct_change"),
                "status": row.get("status"),
            }
            for row in sectors.get("focus_concepts", [])
        ],
        "detailed_boards": [
            {
                "board_type": board.get("board_type"),
                "board_code": board.get("board_code"),
                "board_name": board.get("board_name"),
                "score": board.get("score"),
                "picks": {
                    role: {
                        "code": item.get("code"),
                        "name": item.get("name"),
                        "status": item.get("status"),
                    }
                    for role, item in (board.get("picks") or {}).items()
                },
            }
            for board in sectors.get("detailed_boards", [])
        ],
    }


def write_outputs(
    root: str | Path,
    snapshot: dict[str, Any],
    report: str,
    *,
    active_plans: list[dict[str, Any]] | None = None,
    new_outcomes: list[dict[str, Any]] | None = None,
) -> OutputPaths:
    output_root = Path(root)
    target_date = str(snapshot["target_date"])
    day_dir = output_root / "data" / "processed" / target_date
    report_dir = output_root / "reports"
    state_dir = output_root / "data" / "state"
    day_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = day_dir / "snapshot.json"
    ranking_path = day_dir / "ranking.csv"
    report_path = report_dir / f"{target_date}.md"
    latest_path = state_dir / "latest.json"
    history_path = state_dir / "history.jsonl"

    existing = load_same_day_snapshot(output_root, target_date=target_date)
    if should_preserve(existing, snapshot):
        return OutputPaths(
            report=report_path,
            snapshot=snapshot_path,
            ranking=ranking_path,
            latest=latest_path,
            history=history_path,
            preserved_existing=True,
        )

    text = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    snapshot_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")

    fields = [
        "rank",
        "code",
        "name",
        "data_date",
        "close",
        "pct_change",
        "score",
        "rating",
        "daily_trend",
        "weekly_trend",
        "trend_60m",
        "data_confidence",
        "conclusion",
    ]
    with ranking_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(snapshot.get("stocks", []))

    history: dict[str, dict[str, Any]] = {}
    if history_path.is_file():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("target_date"):
                history[str(item["target_date"])] = item
    history[target_date] = {
        "target_date": target_date,
        "generated_at": snapshot.get("generated_at"),
        "valid_count": snapshot.get("valid_count"),
        "top5": snapshot.get("top5"),
        "sectors": _compact_sectors(snapshot),
        "stocks": [
            {
                "rank": row.get("rank"),
                "code": row.get("code"),
                "score": row.get("score"),
                "rating": row.get("rating"),
                "daily_trend": row.get("daily_trend"),
                "trend_60m": row.get("trend_60m"),
                "levels": row.get("levels"),
            }
            for row in snapshot.get("stocks", [])
        ],
    }
    history_path.write_text(
        "\n".join(json.dumps(history[key], ensure_ascii=False, allow_nan=False) for key in sorted(history)) + "\n",
        encoding="utf-8",
    )
    if active_plans is not None or new_outcomes is not None:
        persist_trade_state(output_root, active_plans or [], new_outcomes or [])
    return OutputPaths(
        report=report_path,
        snapshot=snapshot_path,
        ranking=ranking_path,
        latest=latest_path,
        history=history_path,
    )
