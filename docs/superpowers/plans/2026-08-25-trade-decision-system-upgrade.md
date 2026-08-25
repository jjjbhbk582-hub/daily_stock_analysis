# A股交易决策系统升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将固定59只股票的收盘复盘升级为具备双计划、绝对交易门槛、缺失标记、风险仓位、T+1生命周期和无前视统计的交易决策系统。

**Architecture:** 保留现有分析、排名和报告前九部分，在 `analysis.py` 输出的股票行上追加基本面质量和技术交易评分；由独立政策、计划和追踪模块生成下一交易日决策，并由存储层原子持久化活动计划与不可变结果。报告只渲染结构化 `trade_decision`，不再从相对排名临时推导“推荐”。

**Tech Stack:** Python 3.11–3.13、pandas 2.2、NumPy 1.26、exchange-calendars 4.8、PyYAML 6、pytest 8、Ruff 0.9。

**Spec:** `docs/superpowers/specs/2026-08-25-trade-decision-system-design.md`

## Global Constraints

- 固定股票池保持59只；现有 `schema_version=2`、`top5`、排名CSV和报告前九部分兼容。
- 基本面缺失或过期不直接淘汰技术机会，但必须醒目标记；模型仓位上限分别为7.5%、7.5%，`partial`为10%，`verified`为15%。
- 可执行绝对门槛：行情有效且高置信度、技术评分至少70、日线多头/强势多头、60分钟非空头、第一目标赔率至少1.8、关键价位与ATR完整、无硬风险。
- 回踩与突破必须使用独立入场、止损、止盈、赔率和追高线；突破第一目标严格高于突破入场。
- 每笔模型风险预算为账户0.5%；市场总仓位上限为70%/50%/30%，单行业25%。
- 遵守A股T+1；计划触发当日不模拟退出，缺少分钟顺序的同日止损/止盈标记为 `ambiguous` 且不计统计。
- 滚动统计仅使用真实保存的计划；样本少于30笔时显示“统计置信度不足”。
- 所有生产代码必须先有失败测试；不得使用未来数据回填旧信号。
- 当前工作区已有59只扩容和24日报告未提交改动；不得重置、覆盖或丢弃。
- `AGENTS.md` 禁止未经用户明确确认执行 `git commit`、`git push`、打标签或创建PR；以下提交步骤只作为授权后的检查点，本轮不得执行。

---

### Task 1: 基本面质量与技术交易评分

**Files:**
- Create: `close_review_engine/src/ashare_review/fundamental_quality.py`
- Create: `close_review_engine/tests/test_fundamental_quality.py`
- Modify: `close_review_engine/src/ashare_review/analysis.py`
- Modify: `close_review_engine/src/ashare_review/sector_link.py`

**Interfaces:**
- Consumes: `financials: dict[str, Any]`、`target_date: date`、股票行中的 `score_breakdown`。
- Produces: `assess_fundamentals(financials, target_date, *, announcements=()) -> dict[str, Any]`；`technical_trade_score(score_breakdown) -> float`；每行追加 `fundamental_status`、`fundamental_missing_fields`、`fundamental_report_date`、`fundamental_age_days`、`fundamental_risk_flags`、`technical_trade_score`。

- [ ] **Step 1: 写基本面状态失败测试**

```python
def test_missing_fundamentals_remain_visible_as_technical_only() -> None:
    result = assess_fundamentals({}, date(2026, 8, 24))
    assert result == {
        "fundamental_status": "missing",
        "fundamental_missing_fields": ["report_date", "revenue_yoy", "net_profit_yoy", "roe"],
        "fundamental_report_date": None,
        "fundamental_age_days": None,
        "fundamental_risk_flags": [],
    }

def test_report_older_than_200_days_is_stale() -> None:
    result = assess_fundamentals(
        {"report_date": "2026-01-31", "revenue_yoy": 5, "net_profit_yoy": 6, "roe": 8},
        date(2026, 8, 24),
    )
    assert result["fundamental_status"] == "stale"
    assert result["fundamental_age_days"] == 205
```

- [ ] **Step 2: 验证测试因模块缺失失败**

Run: `cd close_review_engine && pytest tests/test_fundamental_quality.py -v`

Expected: FAIL，错误为 `ModuleNotFoundError: ashare_review.fundamental_quality`。

- [ ] **Step 3: 实现质量判定和硬风险识别**

```python
CORE_FIELDS = ("revenue_yoy", "net_profit_yoy", "roe")
HARD_RISK_WORDS = ("退市", "暂停上市", "ST", "财务造假", "监管立案", "立案调查")

def assess_fundamentals(financials, target_date, *, announcements=()):
    # 解析 report_date；按 missing/partial/stale/verified 判定；
    # 只把有限数值视为已填写；从公告标题提取硬风险词并去重。
```

- [ ] **Step 4: 写技术交易评分失败测试**

```python
def test_technical_trade_score_excludes_fundamental_placeholder() -> None:
    breakdown = {"fundamental": 16, "industry": 14, "trend": 20, "structure": 10, "events": 7}
    assert technical_trade_score(breakdown) == 72.9
```

- [ ] **Step 5: 实现并接入分析行和板块重评分**

```python
def technical_trade_score(breakdown: Mapping[str, Any]) -> float:
    raw = sum(finite(breakdown.get(key), 0.0) or 0.0 for key in ("industry", "trend", "structure", "events"))
    return round(max(0.0, min(100.0, raw / 70.0 * 100.0)), 1)
```

在 `analyze_stock()` 的有效与无效分支都追加质量字段；在 `apply_sector_scores_to_fixed_rows()` 更新行业分后重新计算 `technical_trade_score`，避免使用旧行业分。

- [ ] **Step 6: 运行聚焦测试和既有引擎回归**

Run: `cd close_review_engine && pytest tests/test_fundamental_quality.py tests/test_engine.py -v`

Expected: PASS；59只行全部含新字段，旧字段仍存在。

- [ ] **Step 7: 授权后提交检查点**

```bash
git add close_review_engine/src/ashare_review/fundamental_quality.py close_review_engine/src/ashare_review/analysis.py close_review_engine/src/ashare_review/sector_link.py close_review_engine/tests/test_fundamental_quality.py
git commit -m "feat: add fundamental quality and technical trade score"
```

### Task 2: 版本化政策、双交易计划与绝对门槛

**Files:**
- Create: `close_review_engine/src/ashare_review/trade_policy.py`
- Create: `close_review_engine/src/ashare_review/trade_plans.py`
- Create: `close_review_engine/tests/test_trade_plans.py`
- Modify: `close_review_engine/src/ashare_review/engine.py`

**Interfaces:**
- Consumes: 股票行 `levels`、`metrics.atr_14`、趋势、置信度、基本面状态、板块匹配质量。
- Produces: `TradePolicy`；`build_pullback_plan(row, target_date, valid_for, policy) -> dict[str, Any]`；`build_breakout_plan(...)`；`build_trade_decision(rows, market, target_date, valid_for, policy=DEFAULT_POLICY) -> dict[str, Any]`。

- [ ] **Step 1: 写回踩和突破互相独立的失败测试**

```python
def test_breakout_plan_has_its_own_stop_targets_and_rr() -> None:
    row = make_row(close=10.0, pullback=(9.40, 9.60), breakout=10.20, atr=0.50)
    pullback = build_pullback_plan(row, TARGET, NEXT_DAY, DEFAULT_POLICY)
    breakout = build_breakout_plan(row, TARGET, NEXT_DAY, DEFAULT_POLICY)
    assert pullback["entry"]["reference"] == 9.50
    assert breakout["entry"]["reference"] == 10.20
    assert breakout["stop"] == 9.60
    assert breakout["target_1"] == 11.28
    assert breakout["target_1"] > breakout["entry"]["reference"]
    assert breakout["risk_reward_1"] == 1.8
    assert pullback["stop"] != breakout["stop"]
```

- [ ] **Step 2: 验证测试因模块缺失失败**

Run: `cd close_review_engine && pytest tests/test_trade_plans.py::test_breakout_plan_has_its_own_stop_targets_and_rr -v`

Expected: FAIL，错误为缺少 `trade_plans`。

- [ ] **Step 3: 实现不可变政策参数**

```python
@dataclass(frozen=True, slots=True)
class TradePolicy:
    version: str = "v1"
    min_technical_score: float = 70.0
    watch_technical_score: float = 65.0
    min_rr1: float = 1.8
    breakout_volume_ratio: float = 1.3
    risk_budget_pct: float = 0.5
    max_holding_sessions: int = 5
```

- [ ] **Step 4: 实现双计划价格公式和唯一ID**

实现规范第5节公式，价格统一两位小数，赔率用未四舍五入价格计算后保留两位；计划ID格式严格为 `{target_date}:{code}:{setup}:{policy.version}`，两个计划不得共享 `stop`、`target_1`、`target_2` 或赔率字段来源。

- [ ] **Step 5: 写空仓、等待和技术交易标记失败测试**

```python
def test_absolute_gate_allows_an_empty_executable_list() -> None:
    row = make_row(technical_score=69.9, daily_trend="多头")
    decision = build_trade_decision([row], market_fixture(), TARGET, NEXT_DAY)
    assert decision["executable"] == []
    assert decision["watch_only"][0]["code"] == row["code"]

def test_missing_fundamentals_do_not_hide_a_technical_setup() -> None:
    row = make_row(technical_score=75, fundamental_status="missing", daily_trend="多头")
    decision = build_trade_decision([row], market_fixture(), TARGET, NEXT_DAY)
    plans = decision["ready_next_session"] + decision["waiting_trigger"]
    assert plans
    assert plans[0]["recommendation_type"] == "technical_only"
    assert plans[0]["model_weight_pct"] <= 7.5
```

- [ ] **Step 6: 实现状态分类与降级容错**

`build_trade_decision()` 输出 `status`、`policy_version`、`valid_for`、`market_regime`、`executable`、`ready_next_session`、`waiting_trigger`、`watch_only`、`rejected`、`all_plans`、`errors`；单股异常写入 `errors` 后继续处理，顶层异常由 `engine.py` 降级为 `{"status": "unavailable", "errors": [...]}`。

- [ ] **Step 7: 接入 `run_review()` 并验证快照契约**

Run: `cd close_review_engine && pytest tests/test_trade_plans.py tests/test_engine.py -v`

Expected: PASS；快照含 `trade_decision`，原有排名与Top5不变。

- [ ] **Step 8: 授权后提交检查点**

```bash
git add close_review_engine/src/ashare_review/trade_policy.py close_review_engine/src/ashare_review/trade_plans.py close_review_engine/src/ashare_review/engine.py close_review_engine/tests/test_trade_plans.py close_review_engine/tests/test_engine.py
git commit -m "feat: add independent trade plans and absolute gates"
```

### Task 3: 市场状态、风险仓位与板块质量

**Files:**
- Modify: `close_review_engine/src/ashare_review/comparison.py`
- Modify: `close_review_engine/src/ashare_review/sector_link.py`
- Modify: `close_review_engine/src/ashare_review/trade_plans.py`
- Create: `close_review_engine/tests/test_trade_risk.py`
- Modify: `close_review_engine/tests/test_sector_stock_scoring.py`

**Interfaces:**
- Consumes: 指数涨跌、涨跌家数、中位涨幅、行业涨跌；每个计划的入场与止损；板块 `confidence` 与来源日期。
- Produces: `build_trade_regime(market) -> dict[str, Any]`；`model_weight_pct(entry, stop, fundamental_status, regime_cap, sector_remaining) -> float`；`sector_link.match_quality`、`match_kind`、`eligible_for_trade_gate`。

- [ ] **Step 1: 写三类市场和仓位失败测试**

```python
@pytest.mark.parametrize(
    ("market", "label", "cap"),
    [(risk_on_market(), "risk_on", 70.0), (neutral_market(), "neutral", 50.0), (risk_off_market(), "risk_off", 30.0)],
)
def test_market_regime_sets_portfolio_cap(market, label, cap) -> None:
    regime = build_trade_regime(market)
    assert regime["label"] == label
    assert regime["max_total_weight_pct"] == cap

def test_missing_fundamentals_cap_position_even_with_tight_stop() -> None:
    assert model_weight_pct(10.0, 9.8, "missing", 70.0, 25.0) == 7.5
```

- [ ] **Step 2: 验证风险测试失败**

Run: `cd close_review_engine && pytest tests/test_trade_risk.py -v`

Expected: FAIL，缺少市场状态和仓位接口。

- [ ] **Step 3: 实现0–100市场分和顺序分配仓位**

指数、上涨占比、中位涨跌和行业上涨比例先各自映射到0–100，再按35/35/20/10加权；按 `technical_trade_score`、`risk_reward_1`、固定池排名排序分配剩余市场和行业额度，单股使用 `0.5 / stop_distance_pct * 100`。

- [ ] **Step 4: 写行业优先与低置信度失败测试**

```python
def test_cnooc_prefers_oil_and_gas_extraction_industry_over_petroleum_theme() -> None:
    score, _, matched = calculate_sector_industry_score(cnooc_config(), sector_fixture())
    assert score > 0
    assert matched["board_name"] == "石油和天然气开采"
    assert matched["match_kind"] == "industry_exact_or_alias"

def test_partial_concept_cannot_satisfy_trade_gate() -> None:
    _, _, matched = calculate_sector_industry_score(config_with_theme(), partial_concept_fixture())
    assert matched["eligible_for_trade_gate"] is False
```

- [ ] **Step 5: 修正匹配排序和元数据**

候选排序键固定为：行业精确/别名、行业包含、概念精确/别名、概念包含、板块评分；只有目标日一致且 `confidence=high` 的行业匹配可令 `eligible_for_trade_gate=true`。无合格匹配时保留中性兼容分，但交易门槛视为降级。

- [ ] **Step 6: 运行风险与板块回归**

Run: `cd close_review_engine && pytest tests/test_trade_risk.py tests/test_sector_stock_scoring.py tests/test_sector_fallbacks.py -v`

Expected: PASS。

- [ ] **Step 7: 授权后提交检查点**

```bash
git add close_review_engine/src/ashare_review/comparison.py close_review_engine/src/ashare_review/sector_link.py close_review_engine/src/ashare_review/trade_plans.py close_review_engine/tests/test_trade_risk.py close_review_engine/tests/test_sector_stock_scoring.py
git commit -m "feat: add market regime and risk-budget sizing"
```

### Task 4: 交易日、T+1与计划生命周期

**Files:**
- Modify: `close_review_engine/src/ashare_review/calendar.py`
- Create: `close_review_engine/src/ashare_review/trade_tracking.py`
- Create: `close_review_engine/tests/test_trade_tracking.py`

**Interfaces:**
- Consumes: 活动计划、下一交易日股票OHLC/量能、可选分钟数据、交易日历。
- Produces: `next_trading_day(value: date) -> date`；`evaluate_plan(plan, daily_bar, *, intraday=None) -> tuple[dict[str, Any], dict[str, Any] | None]`；`calculate_trade_statistics(outcomes) -> dict[str, Any]`。

- [ ] **Step 1: 写交易日和跳空取消失败测试**

```python
def test_next_trading_day_skips_weekend() -> None:
    assert next_trading_day(date(2026, 8, 28)) == date(2026, 8, 31)

def test_open_above_no_chase_cancels_pending_plan() -> None:
    updated, outcome = evaluate_plan(pending_plan(no_chase=10.5), bar(open=10.6, high=10.8, low=10.55, close=10.7))
    assert updated["lifecycle_status"] == "cancelled_gap"
    assert outcome["exit_reason"] == "cancelled_gap"
```

- [ ] **Step 2: 验证生命周期测试失败**

Run: `cd close_review_engine && pytest tests/test_trade_tracking.py -v`

Expected: FAIL，缺少接口。

- [ ] **Step 3: 实现 pending、triggered、target1、target2、stopped、timed_exit、expired、cancelled_gap、unfilled、ambiguous 状态机**

触发日只记录 `entry_date`、`entry_price`、MFE/MAE，不检查止盈止损；从下一交易日起处理退出。同一日同时触及止损和目标且没有分钟顺序时终止为 `ambiguous`，`included_in_statistics=false`。

- [ ] **Step 4: 写T+1、减半、移动止损和持有期失败测试**

```python
def test_trigger_day_cannot_stop_out_under_t_plus_one() -> None:
    updated, outcome = evaluate_plan(pending_plan(entry=10.0, stop=9.5), bar(open=10.1, high=10.2, low=9.4, close=9.8))
    assert updated["lifecycle_status"] == "triggered"
    assert outcome is None

def test_target1_reduces_half_and_moves_stop_next_session() -> None:
    updated, outcome = evaluate_plan(triggered_plan(entry=10, target1=11, stop=9.5), bar(open=10.4, high=11.1, low=10.2, close=10.9))
    assert updated["lifecycle_status"] == "target1"
    assert updated["remaining_weight_fraction"] == 0.5
    assert updated["protective_stop"] == 10.0
    assert outcome is None
```

- [ ] **Step 5: 实现统计口径并测试手算样本**

使用三笔非歧义结果 `+10%`、`-5%`、`+5%`，断言样本3、胜率66.67%、平均盈利7.5%、平均亏损-5%、期望3.33%、最大连续亏损1；按 setup、regime、recommendation_type 同口径分组，`confidence="insufficient"`。

- [ ] **Step 6: 运行生命周期全测**

Run: `cd close_review_engine && pytest tests/test_calendar.py tests/test_trade_tracking.py -v`

Expected: PASS。

- [ ] **Step 7: 授权后提交检查点**

```bash
git add close_review_engine/src/ashare_review/calendar.py close_review_engine/src/ashare_review/trade_tracking.py close_review_engine/tests/test_calendar.py close_review_engine/tests/test_trade_tracking.py
git commit -m "feat: track trade plans with A-share settlement rules"
```

### Task 5: 原子存储、昨日验收与统计CLI

**Files:**
- Modify: `close_review_engine/src/ashare_review/storage.py`
- Modify: `close_review_engine/src/ashare_review/engine.py`
- Modify: `close_review_engine/src/ashare_review/cli.py`
- Create: `close_review_engine/tests/test_trade_storage.py`
- Create: `close_review_engine/tests/test_cli.py`

**Interfaces:**
- Consumes: `snapshot.trade_decision.all_plans`、`data/state/trade_plans.json`、`trade_outcomes.jsonl`。
- Produces: `load_trade_state(root) -> tuple[list[dict], list[dict]]`；`persist_trade_state(root, active, new_outcomes) -> None`；`evaluate_saved_trades(root) -> dict`；CLI `ashare-review evaluate-trades --output-root .`。

- [ ] **Step 1: 写原子状态和损坏保护失败测试**

```python
def test_corrupt_active_plan_file_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "data/state/trade_plans.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(TradeStateCorruptError):
        load_trade_state(tmp_path)
    assert path.read_text(encoding="utf-8") == "{broken"
```

- [ ] **Step 2: 验证存储测试失败**

Run: `cd close_review_engine && pytest tests/test_trade_storage.py -v`

Expected: FAIL，缺少存储接口。

- [ ] **Step 3: 实现同目录临时文件加 `Path.replace()` 的原子写入**

活动计划用完整JSON替换；结果日志先读取并按 `plan_id + exit_date + exit_reason` 去重，再以完整JSONL原子替换。损坏文件抛出专用异常且不写任何状态。

- [ ] **Step 4: 把上一交易日验收接入运行编排**

`run_review()` 接受可选 `active_plans` 和 `outcomes`；先用当日股票OHLC推进旧计划，写入 `previous_trade_review` 和 `trade_statistics`，再生成下一交易日计划。`write_outputs()` 在基础报告成功写入后调用 `persist_trade_state()`。

- [ ] **Step 5: 写CLI行为失败测试**

```python
def test_evaluate_trades_prints_saved_statistics_without_mutating_plans(tmp_path: Path, capsys) -> None:
    seed_trade_state(tmp_path)
    before = (tmp_path / "data/state/trade_plans.json").read_bytes()
    assert main(["evaluate-trades", "--output-root", str(tmp_path)]) == 0
    assert '"sample_count"' in capsys.readouterr().out
    assert (tmp_path / "data/state/trade_plans.json").read_bytes() == before
```

- [ ] **Step 6: 实现子命令并运行存储/CLI/引擎回归**

Run: `cd close_review_engine && pytest tests/test_trade_storage.py tests/test_cli.py tests/test_engine.py -v`

Expected: PASS。

- [ ] **Step 7: 授权后提交检查点**

```bash
git add close_review_engine/src/ashare_review/storage.py close_review_engine/src/ashare_review/engine.py close_review_engine/src/ashare_review/cli.py close_review_engine/tests/test_trade_storage.py close_review_engine/tests/test_cli.py
git commit -m "feat: persist and evaluate trade lifecycle"
```

### Task 6: 报告契约与24日缺失标记回归

**Files:**
- Modify: `close_review_engine/src/ashare_review/report.py`
- Create: `close_review_engine/tests/test_trade_report.py`
- Modify: `close_review_engine/tests/test_engine.py`

**Interfaces:**
- Consumes: `snapshot.trade_decision`、`previous_trade_review`、`trade_statistics`。
- Produces: 第十部分的十个子区块；每只计划显示状态、类型、双评分、基本面状态、有效日、触发、入场、止损、双目标、双赔率、模型仓位、失效条件与未入选原因。

- [ ] **Step 1: 写“等待不是买入”和缺失醒目标记失败测试**

```python
def test_report_marks_missing_fundamentals_without_calling_waiting_plan_buyable() -> None:
    report = render_report(snapshot_with_waiting_technical_only_plan())
    assert "技术交易｜基本面缺失" in report
    assert "缺失字段：report_date、revenue_yoy、net_profit_yoy、roe" in report
    assert "等待触发" in report
    assert "现在可以买" not in report
```

- [ ] **Step 2: 验证报告测试失败**

Run: `cd close_review_engine && pytest tests/test_trade_report.py -v`

Expected: FAIL，现有报告仍从 `_trade_recommendations()` 选前两名。

- [ ] **Step 3: 删除临时相对排名推荐逻辑并只渲染结构化决策**

第十部分顺序固定为：市场状态、今日可执行、等待触发、技术交易但基本面缺失、观察与回避、回踩明细、突破明细、推荐依据与缺失字段、昨日验收、累计统计。无合格计划时明确写“今日无可执行交易”。

- [ ] **Step 4: 写双计划字段和统计置信度失败测试**

断言同一股票的回踩/突破入场和止损分别出现、突破目标1大于突破入场、样本少于30时出现“统计置信度不足”、模型仓位不是用户真实持仓建议。

- [ ] **Step 5: 运行报告和59只端到端测试**

Run: `cd close_review_engine && pytest tests/test_trade_report.py tests/test_engine.py -v`

Expected: PASS。

- [ ] **Step 6: 授权后提交检查点**

```bash
git add close_review_engine/src/ashare_review/report.py close_review_engine/tests/test_trade_report.py close_review_engine/tests/test_engine.py
git commit -m "feat: render auditable trade decision report"
```

### Task 7: 自动化、文档与24日报告再生成

**Files:**
- Modify: `close_review_engine/AUTOMATION_PROMPT.md`
- Modify: `close_review_engine/README.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `close_review_engine/data/processed/2026-08-24/snapshot.json`
- Modify: `close_review_engine/data/processed/2026-08-24/ranking.csv`
- Modify: `close_review_engine/data/state/latest.json`
- Modify: `close_review_engine/data/state/history.jsonl`
- Modify: `close_review_engine/reports/2026-08-24.md`

**Interfaces:**
- Consumes: 新CLI、状态文件和报告契约。
- Produces: 自动任务操作手册与24日回归产物；不伪造24日之前的交易结果。

- [ ] **Step 1: 更新自动化契约**

明确每日收盘后先读取活动计划、验收当日、生成下一交易日双计划、写入状态；基础行情失败不得伪造交易建议；状态损坏必须报警并保留原文件；推送需包含“今日可执行/等待触发/基本面缺失/昨日验收/样本置信度”。

- [ ] **Step 2: 更新README与变更记录**

记录四种动作状态、模型仓位含义、T+1和跳空取消、`evaluate-trades` 用法、基本面缺失不会直接屏蔽技术机会及风险限制。

- [ ] **Step 3: 以现有24日已验证数据重新生成报告**

Run: `cd close_review_engine && PYTHONPATH=src python -m ashare_review.cli run --as-of 2026-08-24 --fixture config/review_fixture.yml --force --output-root .`

Expected: `VALID_COUNT=59`、`UNIVERSE_COUNT=59`；快照含 `trade_decision`；报告不把 `waiting_trigger` 写成可立即买入；不生成任何24日以前的虚构结果。

- [ ] **Step 4: 验证结构化产物**

Run: `cd close_review_engine && PYTHONPATH=src python -m ashare_review.cli evaluate-trades --output-root .`

Expected: 输出合法JSON；无历史结束计划时 `sample_count=0` 且 `confidence=insufficient`。

- [ ] **Step 5: 授权后提交检查点**

```bash
git add close_review_engine/AUTOMATION_PROMPT.md close_review_engine/README.md docs/CHANGELOG.md close_review_engine/data close_review_engine/reports/2026-08-24.md
git commit -m "docs: publish auditable trade decision workflow"
```

### Task 8: 全量质量门和验收矩阵

**Files:**
- Modify only if a failing quality gate exposes a defect in files listed above.

**Interfaces:**
- Consumes: 全部实现与测试。
- Produces: 可复现的测试、静态检查、编译、fixture和需求逐项证据。

- [ ] **Step 1: 运行全量测试**

Run: `cd close_review_engine && pytest -q`

Expected: 0 failures。

- [ ] **Step 2: 运行Ruff**

Run: `cd close_review_engine && ruff check src tests`

Expected: `All checks passed!`。

- [ ] **Step 3: 运行Python编译检查**

Run: `cd close_review_engine && python -m compileall -q src tests`

Expected: exit code 0。

- [ ] **Step 4: 验证JSON、CSV和59/59契约**

Run: `cd close_review_engine && python - <<'PY'
import csv, json
from pathlib import Path
p = Path('data/processed/2026-08-24')
s = json.loads((p / 'snapshot.json').read_text(encoding='utf-8'))
rows = list(csv.DictReader((p / 'ranking.csv').open(encoding='utf-8-sig')))
assert s['schema_version'] == 2
assert s['valid_count'] == s['universe_count'] == 59
assert len(s['stocks']) == len(rows) == 59
assert 'trade_decision' in s
assert all('technical_trade_score' in row and 'fundamental_status' in row for row in s['stocks'])
print('24日结构化验收通过：59/59')
PY`

Expected: `24日结构化验收通过：59/59`。

- [ ] **Step 5: 对照规范验收全部关键行为**

逐项确认：空仓机制；基本面缺失仍可作为技术候选且仓位不超过7.5%；双计划独立；突破目标严格高于入场；等待触发不写成可以买；T+1、跳空和歧义；少于30笔置信度不足；旧字段兼容；板块低置信度不可通过门槛。

- [ ] **Step 6: 检查改动边界和未提交状态**

Run: `git diff --check && git status --short`

Expected: `git diff --check` 无输出；状态只包含本计划和此前用户授权范围内的文件，没有提交或推送。

- [ ] **Step 7: 用户明确授权后再提交/推送**

```bash
git add close_review_engine docs/superpowers docs/CHANGELOG.md
git commit -m "feat: upgrade A-share trade decision system"
git push
```

本步骤在用户再次明确说“提交并推送”之前不得执行。
