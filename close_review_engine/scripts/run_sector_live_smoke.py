from __future__ import annotations

import argparse
import json
from datetime import date

from ashare_review.calendar import last_completed_trading_day
from ashare_review.config import load_universe
from ashare_review.engine import build_live_source
from ashare_review.sector_runtime import build_sector_review

ALLOWED_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def main() -> int:
    parser = argparse.ArgumentParser(description="联网验证板块全景与2+2动态候选")
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="目标交易日；默认使用北京时间最近一个已完成的沪深交易日",
    )
    parser.add_argument("--universe", default="config/universe.yml")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-industries", type=int, default=50)
    parser.add_argument("--min-concepts", type=int, default=100)
    args = parser.parse_args()
    target_date = args.as_of or last_completed_trading_day()

    source = build_live_source()
    universe = load_universe(args.universe)
    market = source.load_market(universe[:3], target_date)
    sectors = build_sector_review(
        source,
        market,
        target_date=target_date,
        previous_snapshot=None,
        max_workers=max(1, min(args.workers, 8)),
    )

    errors: list[str] = []
    industry = sectors.get("industry_ranking") or []
    concept = sectors.get("concept_ranking") or []
    detailed = sectors.get("detailed_boards") or []
    dynamic = sectors.get("dynamic_candidates") or []

    industry_codes = {str(row.get("board_code") or "") for row in industry}
    concept_codes = {str(row.get("board_code") or "") for row in concept}
    industry_names = {str(row.get("board_name") or "") for row in industry}
    concept_names = {str(row.get("board_name") or "") for row in concept}
    if len(industry) < args.min_industries:
        errors.append(f"行业板块不足：{len(industry)} < {args.min_industries}")
    if len(industry) > 200:
        errors.append(f"行业分类数量异常：{len(industry)} > 200")
    if len(concept) < args.min_concepts:
        errors.append(f"概念板块不足：{len(concept)} < {args.min_concepts}")
    if len(industry_codes) != len(industry) or len(industry_names) != len(industry):
        errors.append("行业板块存在重复代码或名称")
    if len(concept_codes) != len(concept) or len(concept_names) != len(concept):
        errors.append("概念板块存在重复代码或名称")
    if len(sectors.get("top_boards") or []) != 5:
        errors.append("强势板块Top5不完整")
    if not detailed or len(detailed) > 7:
        errors.append(f"详细板块数量异常：{len(detailed)}")
    if len(sectors.get("focus_concepts") or []) < 12:
        errors.append("固定重点概念不完整")
    if not dynamic:
        errors.append("未生成任何动态2+2候选")

    target = target_date.isoformat()
    for row in [*industry, *concept]:
        if row.get("data_date") != target:
            errors.append(
                f"板块日期不符：{row.get('board_name')}={row.get('data_date')}，目标={target}"
            )
            break
    for item in dynamic:
        code = str(item.get("code") or "")
        close = float(item.get("close") or 0)
        name = str(item.get("name") or "")
        if not code.startswith(ALLOWED_PREFIXES):
            errors.append(f"非沪深主板候选：{code}")
        if not 0 < close <= 100:
            errors.append(f"候选超过100元或价格无效：{code}={close}")
        if "ST" in name.upper() or "退" in name:
            errors.append(f"风险名称候选：{code} {name}")

    payload = {
        "target_date": target,
        "industry_count": len(industry),
        "industry_unique_codes": len(industry_codes),
        "concept_count": len(concept),
        "concept_unique_codes": len(concept_codes),
        "focus_ready": sum(
            row.get("status") == "ready" for row in sectors.get("focus_concepts", [])
        ),
        "top_boards": [row.get("board_name") for row in sectors.get("top_boards", [])],
        "detailed_board_count": len(detailed),
        "dynamic_candidate_count": len(dynamic),
        "dynamic_candidates": [
            {
                "board": row.get("board_name"),
                "role": row.get("role_label"),
                "code": row.get("code"),
                "name": row.get("name"),
                "close": row.get("close"),
            }
            for row in dynamic
        ],
        "source_status": sectors.get("source_status"),
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if errors:
        print("SECTOR_LIVE_SMOKE_ERRORS=" + "；".join(errors))
        return 1
    print("SECTOR_LIVE_SMOKE_STATUS=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
