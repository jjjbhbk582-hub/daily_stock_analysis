# Sector 2+2 Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full sector ranking, focus-concept monitoring, and role-based 2+2 dynamic stock candidates to the existing 17-stock A-share close-review engine.

**Architecture:** Keep the fixed 17-stock pipeline unchanged and add an isolated sector subsystem. The sector subsystem fetches board overview/history/constituents, computes deterministic board scores, shortlists eligible main-board stocks under CNY 100, reuses the existing stock analyzer for technical plans, then writes sector results beside—not inside—the fixed universe ranking.

**Tech Stack:** Python 3.12, pandas, numpy, requests, PyYAML, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-21-sector-2plus2-monitoring-design.md`

## Global Constraints

- Dynamic picks allow only prefixes `600`, `601`, `603`, `605`, `000`, `001`, `002`, `003`.
- Target-day close must be `0 < close <= 100.00`.
- Exclude names containing `ST`, `*ST`, or `退`.
- Exclude zero-volume, suspended, one-price limit and sub-CNY-300-million turnover rows.
- Do not mutate the fixed 17-stock universe.
- Do not force four picks when fewer than four stocks qualify.
- Use only completed target-day daily bars.
- Keep production runtime within 45 minutes.

---

### Task 1: Sector configuration and deterministic eligibility

**Files:**
- Create: `close_review_engine/config/sector_monitor.yml`
- Create: `close_review_engine/src/ashare_review/sector_config.py`
- Create: `close_review_engine/tests/test_sector_config.py`

**Interfaces:**
- Produces: `SectorMonitorConfig`, `FocusConcept`, `load_sector_monitor(path)`, `is_eligible_main_board(row, config)`.
- Consumes: plain mappings from board constituent snapshots.

- [ ] **Step 1: Write failing tests**

```python
def test_candidate_filter_enforces_market_price_and_risk_rules():
    config = load_sector_monitor("config/sector_monitor.yml")
    assert is_eligible_main_board({"code": "600000", "name": "浦发银行", "close": 12.0, "amount": 500_000_000, "volume": 1, "high": 12.3, "low": 11.8, "pct_change": 1.2}, config)
    assert not is_eligible_main_board({"code": "300308", "name": "中际旭创", "close": 80.0, "amount": 5_000_000_000, "volume": 1, "high": 82, "low": 79, "pct_change": 2}, config)
    assert not is_eligible_main_board({"code": "600001", "name": "示例", "close": 100.01, "amount": 500_000_000, "volume": 1, "high": 101, "low": 99, "pct_change": 1}, config)
    assert not is_eligible_main_board({"code": "600002", "name": "ST示例", "close": 10, "amount": 500_000_000, "volume": 1, "high": 10.5, "low": 9.5, "pct_change": 1}, config)
```

- [ ] **Step 2: Run the focused test and confirm import failure**

Run: `python -m pytest tests/test_sector_config.py -q`
Expected: FAIL because `ashare_review.sector_config` does not exist.

- [ ] **Step 3: Implement configuration loader and filter**

```python
@dataclass(frozen=True, slots=True)
class SectorMonitorConfig:
    max_price: float
    min_amount: float
    max_detailed_boards: int
    shortlist_per_board: int
    max_dynamic_stocks: int
    focus_concepts: tuple[FocusConcept, ...]


def is_eligible_main_board(row: Mapping[str, Any], config: SectorMonitorConfig) -> bool:
    code = str(row.get("code") or "").zfill(6)
    name = str(row.get("name") or "")
    close = finite(row.get("close"))
    amount = finite(row.get("amount"), 0.0) or 0.0
    high = finite(row.get("high"))
    low = finite(row.get("low"))
    pct = abs(finite(row.get("pct_change"), 0.0) or 0.0)
    prefix_ok = code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))
    one_price_limit = high is not None and low is not None and abs(high - low) < 1e-8 and pct >= 9.5
    return prefix_ok and close is not None and 0 < close <= config.max_price and amount >= config.min_amount and not any(flag in name.upper() for flag in ("ST", "*ST", "退")) and not one_price_limit
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_sector_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -- close_review_engine/config/sector_monitor.yml close_review_engine/src/ashare_review/sector_config.py close_review_engine/tests/test_sector_config.py
git commit -m "feat: add sector monitoring configuration and eligibility"
```

### Task 2: Board data provider contracts

**Files:**
- Create: `close_review_engine/src/ashare_review/sector_data.py`
- Create: `close_review_engine/tests/test_sector_data.py`
- Modify: `close_review_engine/src/ashare_review/fixture.py`
- Modify: `close_review_engine/config/review_fixture.yml`

**Interfaces:**
- Produces: `BoardSnapshot`, `SectorDataProvider`, `fetch_board_overview`, `fetch_board_history`, `fetch_board_constituents`.
- `FixtureDataSource` gains `load_sector_overview(target_date)`, `load_sector_history(board_type, board_code, target_date)`, and `load_sector_constituents(board_type, board_code, target_date)`.

- [ ] **Step 1: Add parser contract tests**

```python
def test_board_overview_normalizes_eastmoney_fields():
    rows = normalize_board_overview([{"f12": "BK0001", "f14": "通信设备", "f3": 2.1, "f8": 3.2, "f104": 70, "f105": 20, "f128": "龙头A", "f136": 9.9}], "industry")
    assert rows[0]["board_code"] == "BK0001"
    assert rows[0]["board_type"] == "industry"
    assert rows[0]["up_count"] == 70
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_sector_data.py -q`
Expected: FAIL because provider functions do not exist.

- [ ] **Step 3: Implement the HTTP provider**

Use Eastmoney board list filters `m:90 t:2 f:!50` for industry and `m:90 t:3 f:!50` for concepts. Use `90.<BK code>` K-lines for 30 completed daily bars and `b:<BK code> f:!50` for constituents. Normalize fields to snake_case and retain `source`, `data_date`, and error status.

- [ ] **Step 4: Add deterministic fixture board data**

The fixture must include at least eight industry/concept boards, 30-day history, and six eligible constituents per detailed board so role selection can be tested without network access.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_sector_data.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -- close_review_engine/src/ashare_review/sector_data.py close_review_engine/tests/test_sector_data.py close_review_engine/src/ashare_review/fixture.py close_review_engine/config/review_fixture.yml
git commit -m "feat: add sector overview history and constituent providers"
```

### Task 3: Board scoring and detailed-board selection

**Files:**
- Create: `close_review_engine/src/ashare_review/sector_analysis.py`
- Create: `close_review_engine/tests/test_sector_analysis.py`

**Interfaces:**
- Produces: `score_board(board, history, market_median)`, `rank_boards(...)`, `select_detailed_boards(current, previous, config)`, `compare_sector_rankings(previous, current)`.

- [ ] **Step 1: Write scoring tests**

```python
def test_healthy_broad_advance_scores_above_one_stock_spike():
    healthy = board_fixture(pct_change=2.5, up_count=80, down_count=20, amount_ratio=1.4, return_5d=5, return_20d=12, limit_up_count=4)
    spike = board_fixture(pct_change=6.0, up_count=18, down_count=62, amount_ratio=2.8, return_5d=-1, return_20d=-4, limit_up_count=1)
    assert score_board(healthy, market_median=0.3)["score"] > score_board(spike, market_median=0.3)["score"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_sector_analysis.py -q`
Expected: FAIL because `sector_analysis` does not exist.

- [ ] **Step 3: Implement the 100-point model**

Implement six clamped components with exact maxima 20/20/20/15/15/10. Return `score_breakdown`, `confidence`, `risk_flags`, `return_5d`, `return_20d`, and `amount_ratio_20`.

- [ ] **Step 4: Implement top5, rising2 and weak3 selection**

Detailed boards are the unique union of top five scores and up to two boards whose same-type rank improved by more than two positions. Cap at `max_detailed_boards`. Return bottom three as risk-only boards.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_sector_analysis.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -- close_review_engine/src/ashare_review/sector_analysis.py close_review_engine/tests/test_sector_analysis.py
git commit -m "feat: score and rank industry and concept boards"
```

### Task 4: Dynamic shortlist and 2+2 role assignment

**Files:**
- Create: `close_review_engine/src/ashare_review/sector_candidates.py`
- Create: `close_review_engine/tests/test_sector_candidates.py`

**Interfaces:**
- Produces: `shortlist_constituents(rows, config)`, `make_dynamic_stock_config(row, board)`, `assign_roles(board, analyzed_rows, config)`.
- Consumes analyzed stock rows produced by existing `analyze_stock`.

- [ ] **Step 1: Write role uniqueness and hard-filter tests**

```python
def test_assign_roles_never_reuses_a_stock_and_never_forces_missing_roles():
    picks = assign_roles(board_fixture(), candidate_rows_fixture(count=3), config_fixture())
    chosen = [item["code"] for item in picks.values() if item.get("code")]
    assert len(chosen) == len(set(chosen))
    assert sum(bool(item.get("code")) for item in picks.values()) == 3
    assert any(item.get("status") == "no_qualified_stock" for item in picks.values())
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_sector_candidates.py -q`
Expected: FAIL because role functions do not exist.

- [ ] **Step 3: Implement shortlist scoring**

Use constituent amount, turnover, current strength and non-limit trading status to retain at most eight candidates per board. Deduplicate globally before loading technical data.

- [ ] **Step 4: Implement role scores**

- Capacity leader: amount percentile, market-cap percentile, daily/weekly trend and confidence.
- Momentum leader: board-relative pct rank, turnover rank, 60-minute trend and breakout pattern.
- Pullback potential: ready levels, daily trend, pullback-zone distance, relative volume no greater than 1.05, and non-strong-bear 60-minute trend.
- Breakout potential: ready trigger, trigger distance from 0% to 4%, daily trend at least偏多震荡, non-strong-bear 60-minute trend, and improving relative volume.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_sector_candidates.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -- close_review_engine/src/ashare_review/sector_candidates.py close_review_engine/tests/test_sector_candidates.py
git commit -m "feat: add sector 2+2 candidate assignment"
```

### Task 5: Engine integration and history persistence

**Files:**
- Modify: `close_review_engine/src/ashare_review/engine.py`
- Modify: `close_review_engine/src/ashare_review/storage.py`
- Modify: `close_review_engine/src/ashare_review/comparison.py`
- Modify: `close_review_engine/tests/test_engine.py`

**Interfaces:**
- Produces: `snapshot["sectors"]`, schema version 2, sector comparison and dynamic candidates.

- [ ] **Step 1: Extend end-to-end tests**

```python
def test_fixture_pipeline_contains_sector_rankings_and_2plus2():
    snapshot = build_snapshot(Path("."))
    sectors = snapshot["sectors"]
    assert sectors["industry_ranking"]
    assert len(sectors["top_boards"]) == 5
    assert len(sectors["detailed_boards"]) <= 7
    for board in sectors["detailed_boards"]:
        codes = [pick["code"] for pick in board["picks"].values() if pick.get("code")]
        assert len(codes) == len(set(codes))
        assert all(float(pick["close"]) <= 100 for pick in board["picks"].values() if pick.get("code"))
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_engine.py -q`
Expected: FAIL because the snapshot has no `sectors` key.

- [ ] **Step 3: Integrate sector review after fixed-stock analysis**

Call the sector subsystem with the same target date and source. Load dynamic stock bundles concurrently, reuse `analyze_stock`, and keep fixed `stocks`/`top5` unchanged.

- [ ] **Step 4: Persist compact sector history**

Write board rank/score, top board codes, focus-concept states and role code assignments into `history.jsonl`. Extend same-day preservation to prefer greater sector completeness only after fixed valid count and high-confidence counts are tied.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_engine.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -- close_review_engine/src/ashare_review/engine.py close_review_engine/src/ashare_review/storage.py close_review_engine/src/ashare_review/comparison.py close_review_engine/tests/test_engine.py
git commit -m "feat: integrate sector review and history comparison"
```

### Task 6: Ten-part report and output contract

**Files:**
- Modify: `close_review_engine/src/ashare_review/report.py`
- Modify: `close_review_engine/scripts/verify_outputs.py`
- Modify: `close_review_engine/tests/test_engine.py`
- Modify: `close_review_engine/README.md`

**Interfaces:**
- Produces the ten-part Markdown report described in the spec.

- [ ] **Step 1: Add report contract tests**

```python
def test_report_contains_sector_panorama_and_2plus2_sections(tmp_path):
    report = render_report(build_snapshot(tmp_path))
    for heading in ("第二部分：行业板块完整排名", "第三部分：重点概念板块", "第五部分：重点板块2+2", "第八部分：动态候选买点"):
        assert heading in report
    assert "资金容量龙头" in report
    assert "弹性龙头" in report
    assert "缩量回踩潜力" in report
    assert "放量突破潜力" in report
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_engine.py -q`
Expected: FAIL because the old five-part report is still rendered.

- [ ] **Step 3: Render board tables and candidate details**

Industry ranking must include rank, daily/5d/20d returns, amount, amount ratio, breadth, limit-ups, score and confidence. Concept section must show top concepts and all configured focus concepts. Each detailed board must show exactly four named role rows, including explicit unavailable rows when necessary.

- [ ] **Step 4: Update verifier and README**

The verifier checks schema version 2, sector keys, fixed 17 rows, fixed Top5, detailed-board cap, role uniqueness, price cap and all report headings.

- [ ] **Step 5: Run the complete quality gate**

Run:

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q src scripts tests
rm -rf /tmp/a-share-sector-ci
ashare-review run --as-of 2026-08-20 --force --fixture config/review_fixture.yml --output-root /tmp/a-share-sector-ci
python scripts/verify_outputs.py /tmp/a-share-sector-ci 2026-08-20
```

Expected: all commands PASS.

- [ ] **Step 6: Commit**

```bash
git add -- close_review_engine/src/ashare_review/report.py close_review_engine/scripts/verify_outputs.py close_review_engine/tests/test_engine.py close_review_engine/README.md
git commit -m "feat: publish sector panorama and 2+2 report"
```

### Task 7: Production workflow verification

**Files:**
- Modify only if required: `.github/workflows/a-share-close-review.yml`
- Modify only if required: `.github/workflows/a-share-close-review-ci.yml`

**Interfaces:**
- Production output remains under `close_review_engine/reports`, `data/processed`, and `data/state`.

- [ ] **Step 1: Confirm CI path coverage**

Verify that changes under `close_review_engine/**` trigger the dedicated CI and that the scheduled workflow timeout is at least 45 minutes.

- [ ] **Step 2: Run PR CI**

Expected checks: unit tests, Ruff, compileall, CLI, 17-stock fixture, sector output verifier.

- [ ] **Step 3: Review generated fixture report**

Confirm no dynamic pick violates the main-board/price/ST/liquidity rules and no board has duplicate role codes.

- [ ] **Step 4: Commit workflow adjustment only if necessary**

```bash
git add -- .github/workflows/a-share-close-review.yml .github/workflows/a-share-close-review-ci.yml
git commit -m "ci: validate sector 2+2 close review"
```
