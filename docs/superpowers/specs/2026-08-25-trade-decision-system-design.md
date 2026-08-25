# A股复盘交易决策系统升级设计

## 1. 目标

在现有59只固定股票复盘、板块2+2和关键价位基础上，增加一套可验证、可降级、可追踪的交易决策层。系统必须区分“股票排名靠前”“技术条件值得观察”“下一交易日可执行”和“基本面完整的综合推荐”，不得把相对排名直接表述为买入建议。

本次升级按以下优先级实施：

1. 分离回踩交易与突破交易的入场、止损、目标和风险收益比；
2. 增加绝对推荐门槛、空仓机制和基本面缺失标记；
3. 增加推荐生命周期、昨日计划验收和滚动回测统计；
4. 增加量化触发、风险预算仓位、A股T+1、跳空和组合集中度规则；
5. 修正板块匹配与扩展数据置信度，更新报告和自动推送契约。

## 2. 非目标

- 不自动下单，不连接券商交易接口；
- 不承诺收益，不把历史统计当作未来收益保证；
- 不通过增加更多相似技术指标替代交易纪律；
- 不在缺少用户实际持仓时伪造个性化组合仓位；
- 不用未来数据回填历史信号，不对旧快照进行带前视偏差的“回测”；
- 不改变固定59只股票池，也不把动态板块候选自动加入固定池。

## 3. 总体架构

新增独立交易决策层，放在股票分析与板块评分之后、报告渲染与存储之前：

1. `analysis.py`继续负责行情指标、趋势、形态和基础关键价位；
2. `fundamental_quality.py`负责基本面完整性、时效性和风险标记；
3. `trade_policy.py`集中保存版本化门槛和风险参数；
4. `trade_plans.py`生成回踩与突破两套独立计划，计算技术交易评分、动作状态和模型仓位；
5. `trade_tracking.py`根据连续交易日快照推进计划状态并统计结果；
6. `engine.py`在快照中追加`trade_decision`，保持现有股票字段兼容；
7. `storage.py`持久化活动计划和已结束结果；
8. `report.py`渲染可执行、等待触发、观察、回避和昨日验收。

现有`snapshot.json`继续使用`schema_version=2`，全部新字段采用追加方式，避免破坏既有自动任务和消费者。

## 4. 双评分与基本面状态

### 4.1 评分

保留现有100分综合评分用于历史排名：

- 基本面30分；
- 行业景气20分；
- 日线与周线趋势25分；
- 60分钟与量价结构15分；
- 事件与风险10分。

新增技术交易评分：

```text
technical_raw = industry + trend + structure + events
technical_trade_score = round(technical_raw / 70 * 100, 1)
```

基本面缺失时，现有综合评分中的中性占位分只为兼容历史排名，必须附带`fundamental_status`，且不得作为推荐依据。交易决策使用`technical_trade_score`和独立的基本面状态，不以占位分冒充已验证基本面。

### 4.2 基本面状态

每只股票追加：

```json
{
  "fundamental_status": "verified | partial | missing | stale",
  "fundamental_missing_fields": [],
  "fundamental_report_date": "YYYY-MM-DD | null",
  "fundamental_age_days": 0,
  "fundamental_risk_flags": []
}
```

判定规则：

- `verified`：`report_date`可解析且距目标日不超过200天，`revenue_yoy`、`net_profit_yoy`、`roe`全部为有限数值；
- `partial`：存在财务记录，但上述必需字段或有效报告日期至少缺少一项；
- `missing`：没有财务记录或三个核心指标全部缺失；
- `stale`：报告日期可解析但距目标日超过200天。

基本面`missing`或`stale`不会直接淘汰短线技术机会，但必须：

- 标记为“技术交易｜基本面缺失/过期”；
- 单股模型仓位上限减半至7.5%；
- 默认最大持有期为5个交易日；
- 禁止标为“综合推荐”；
- 在报告中逐项列出缺失字段。

`partial`的单股模型仓位上限为10%；`verified`上限为15%。明确的重大退市、暂停上市、ST、财务造假、监管立案或无法交易风险可直接否决技术信号。

## 5. 交易计划模型

### 5.1 数据结构

每个候选生成独立计划：

```json
{
  "plan_id": "2026-08-24:600938:pullback:v1",
  "code": "600938",
  "name": "中国海油",
  "setup": "pullback | breakout",
  "decision_status": "ready_next_session | waiting_trigger | watch_only | rejected",
  "recommendation_type": "comprehensive | technical_only",
  "valid_for": "YYYY-MM-DD",
  "expires_after": "YYYY-MM-DD",
  "entry": {"low": 0.0, "high": 0.0, "reference": 0.0},
  "trigger": {},
  "stop": 0.0,
  "target_1": 0.0,
  "target_2": 0.0,
  "risk_reward_1": 0.0,
  "risk_reward_2": 0.0,
  "model_weight_pct": 0.0,
  "reasons": [],
  "rejection_reasons": []
}
```

`valid_for`必须是目标日期后的下一沪深交易日。未触发计划在该日收盘后过期并由新报告重新计算。

### 5.2 回踩计划

回踩区继续由EMA10、EMA20、MA20、近20日突破位和ATR形成支撑共振区。计算口径：

```text
entry_reference = (pullback_low + pullback_high) / 2
risk = entry_reference - pullback_stop
target_1 = max(nearest_resistance, entry_reference + 1.8 * risk)
target_2 = max(prior_60_high, entry_reference + 3.0 * risk)
```

回踩触发要求：

1. 价格进入`pullback_low`至`pullback_high`；
2. 后续30或60分钟K线收回回踩区中枢之上；
3. 确认K线没有继续创出本轮新低；
4. 60分钟趋势不是`空头`或`强势空头`；
5. 未触发跳空取消规则。

只有日线数据时，系统只能标记“日线近似触发”，不得伪装成已验证60分钟触发。

### 5.3 突破计划

突破计划不得复用回踩计划的风险收益比：

```text
breakout_entry = breakout_trigger
candidate_stop = max(pullback_high, breakout_entry - 1.2 * ATR)
breakout_stop = min(breakout_entry - 0.4 * ATR, candidate_stop)
risk = breakout_entry - breakout_stop
target_1 = max(next_resistance_above_entry, breakout_entry + 1.8 * risk)
target_2 = max(target_1 + 0.8 * ATR, breakout_entry + 3.0 * risk)
breakout_no_chase = breakout_entry + 0.5 * risk
```

突破触发要求：

1. 60分钟收盘价不低于突破价；
2. 同时段成交量不低于过去20个同时间段均量的1.3倍；
3. 不是盘中瞬间越过后重新收回压力位下方；
4. 若只有日线数据，则要求日线收盘不低于突破价且日线相对20日均量不低于1.3倍，并标记“日线确认”。

突破计划的第一目标必须严格高于突破入场价。

## 6. 推荐门槛与动作状态

### 6.1 绝对门槛

进入交易候选必须同时满足：

- `data_valid=true`；
- 行情`data_confidence=high`；
- `technical_trade_score >= 70`；
- 日线为`多头`或`强势多头`；
- 60分钟不是`空头`或`强势空头`；
- 当前价格低于对应计划的禁止追高价；
- 对应计划`risk_reward_1 >= 1.8`；
- 没有硬否决风险标记；
- 关键价位和ATR完整。

技术评分65至69.9、日线为`偏多震荡`或行情置信度为`medium`的股票只能进入观察层。任何股票未通过绝对门槛时，报告必须允许“今日无可执行交易”，不得为了凑数选前两名。

### 6.2 状态

- `ready_next_session`：目标日收盘已经形成合格交易结构，下一交易日仍需通过跳空和触发规则；
- `waiting_trigger`：达到候选门槛，但尚未进入回踩区或尚未完成放量突破；
- `watch_only`：技术评分、趋势、数据完整度或赔率接近但未达到门槛；
- `rejected`：明确空头、追高、赔率不足、硬风险或数据不可用。

报告不得把`waiting_trigger`写成“现在可以买”。

## 7. 市场状态与模型仓位

市场状态追加`market.trade_regime`：

```json
{
  "score": 0.0,
  "label": "risk_on | neutral | risk_off",
  "max_total_weight_pct": 0.0,
  "evidence": []
}
```

市场分数使用当日可验证数据：三大指数平均涨跌、上涨家数占比、市场中位涨跌幅、行业上涨比例。权重分别为35%、35%、20%、10%。分数60以上为`risk_on`，45至59.9为`neutral`，低于45为`risk_off`。

组合仓位上限：

- `risk_on`：70%；
- `neutral`：50%；
- `risk_off`：30%；
- 单行业模型仓位：25%。

单股模型仓位：

```text
stop_distance_pct = (entry_reference - stop) / entry_reference * 100
raw_weight_pct = 0.5 / stop_distance_pct * 100
model_weight_pct = min(raw_weight_pct, fundamental_status_cap, remaining_market_cap, remaining_sector_cap)
```

其中0.5表示每笔最多损失账户资金的0.5%。没有用户实际持仓数据时，报告必须写“模型仓位上限”，不得声称已完成真实组合风险校验。

## 8. A股交易约束

- 下一交易日开盘价高于计划禁止追高价：计划取消；
- 下一交易日开盘价低于或等于计划止损价：计划取消，不逆势接单；
- 一字涨停、停牌或无法合理成交：标记`unfilled`；
- 计划触发当日遵守T+1，不在同一交易日模拟卖出；
- 止损和止盈从触发后的下一交易日起生效；
- 第一目标成交后视为减仓50%，从下一交易日起把剩余仓位保护止损上移至入场参考价；
- 第二目标成交、止损成交或持有满5个交易日后结束计划；
- 缺少分钟级顺序且同一天同时触及止损与目标时，标记`ambiguous`，不计入胜率与期望收益。

## 9. 推荐生命周期与滚动回测

活动计划状态：

```text
pending -> triggered -> target1 -> target2
                    -> stopped
                    -> timed_exit
pending -> expired | cancelled_gap | unfilled
任意可判定状态 -> ambiguous
```

持久化文件：

- `data/state/trade_plans.json`：尚未结束的活动计划；
- `data/state/trade_outcomes.jsonl`：结束计划的不可变结果记录；
- `data/processed/YYYY-MM-DD/snapshot.json`：当日`trade_decision`和`previous_trade_review`。

每日报告先验收上一交易日计划，再生成下一交易日计划。验收字段包括：是否触发、模拟入场价、最高有利变动MFE、最大不利变动MAE、目标/止损状态、持有交易日和结束原因。

滚动统计只使用当时真实生成并保存的计划，不从今天的算法倒推旧信号。输出：

- 已结束且非歧义样本数；
- 胜率；
- 平均盈利、平均亏损；
- 平均盈亏比；
- 单笔期望收益；
- 最大连续亏损；
- 模拟权益最大回撤；
- 回踩与突破分组表现；
- `risk_on`、`neutral`、`risk_off`分组表现；
- `verified`和`technical_only`分组表现。

样本数少于30时必须显示“统计置信度不足”，不得输出高置信度胜率结论。

新增CLI子命令：

```text
ashare-review evaluate-trades --output-root .
```

该命令重建并校验已保存计划的滚动统计，不修改历史计划，不下载未来数据。

## 10. 板块与数据质量

- 固定股行业评分优先匹配行业板块的精确名称和配置别名，再考虑概念主题；
- 行业精确匹配优先级必须高于主题子串匹配；
- 板块匹配结果追加`match_quality`和`match_kind`；
- 概念板块缺少5日/20日历史或广度数据时，不得用中性值伪装为完整动态评分；
- `confidence=partial`或来源日期不等于目标交易日的板块不得参与可执行推荐门槛；
- 中国海油不得仅因“石油”主题子串错误匹配到石油加工板块；应优先匹配石油和天然气开采相关行业；
- 所有降级必须进入`reasons`或`rejection_reasons`并在报告可见。

## 11. 报告结构

原十一部分保持兼容，第十部分“推荐交易计划”改为：

1. 市场交易状态与模型总仓位上限；
2. 今日可执行；
3. 等待触发；
4. 技术交易但基本面缺失；
5. 观察与回避；
6. 回踩计划明细；
7. 突破计划明细；
8. 推荐依据与缺失字段；
9. 昨日计划验收；
10. 累计统计与样本置信度。

每只股票至少显示：动作状态、推荐类型、技术评分、综合评分、基本面状态、有效交易日、触发规则、入场、止损、两档止盈、两档赔率、模型仓位、失效条件和未入选原因。

## 12. 错误处理与兼容

- 交易决策层异常不得破坏59只股票基础复盘；快照降级为`trade_decision.status=unavailable`并记录错误类型；
- 活动计划文件损坏时不覆盖原文件，生成错误提示并拒绝伪造历史统计；
- 单只股票计划失败只影响该股票，其他股票继续生成；
- `trade_plans.json`和`trade_outcomes.jsonl`采用原子写入；
- 旧快照没有交易决策字段时继续可读，但不能进入滚动统计；
- 现有`top5`、股票排名CSV和报告前九部分继续保留。

## 13. 测试策略

所有生产代码遵循测试先行：

1. 计划计算单元测试：回踩与突破的入场、止损、目标和赔率互相独立，突破目标严格高于突破价；
2. 基本面状态测试：完整、部分、缺失、过期和硬风险；
3. 推荐门槛测试：绝对门槛、空仓、观察、技术交易标记；
4. 市场状态与仓位测试：三类市场、止损距离、基本面减仓和行业上限；
5. 生命周期测试：触发、T+1、止盈、止损、跳空取消、过期、歧义；
6. 统计测试：胜率、期望收益、连续亏损、最大回撤、样本不足；
7. 板块匹配回归测试：中国海油行业优先、低置信度概念不参与门槛；
8. 报告契约测试：可执行/等待/观察/空仓、缺失字段、双计划、昨日验收；
9. fixture端到端测试：59/59股票、兼容旧字段、生成新的状态文件；
10. 24日快照回归测试：基本面缺失有醒目标记，回踩与突破赔率不混用，不把等待触发写成已可以买入。

## 14. 实施顺序

### 阶段一：计划与门槛

新增政策、基本面质量和双计划模块，接入快照但暂不启用历史状态写入。报告先完成可执行、等待触发、观察和空仓区分。

### 阶段二：生命周期与统计

新增活动计划、结果日志、上一日验收、T+1与跳空状态流转和`evaluate-trades`，以连续新快照开始积累无前视偏差样本。

### 阶段三：风险与数据质量

接入市场状态、风险预算仓位、行业集中度、行业优先匹配和低置信度板块降级。

### 阶段四：文档与自动任务

更新报告模板、`AUTOMATION_PROMPT.md`、验证脚本、README能力概览、专题文档和`docs/CHANGELOG.md`，重新生成24日报告作为回归证据。

## 15. 验收标准

- 没有股票通过绝对门槛时，报告明确显示空仓；
- 基本面缺失股票仍可成为技术交易候选，但标记缺失、仓位上限7.5%、最长5个交易日；
- 回踩与突破拥有不同止损、目标和风险收益比；
- 突破第一目标严格高于突破入场价；
- 等待触发不会被写成现在可以买；
- 每日计划具有唯一ID、指定有效交易日和可追踪状态；
- T+1、跳空和同日歧义按本规范处理；
- 统计不足30笔时显示置信度不足；
- 旧快照和现有报告消费者保持可用；
- 全量单元测试、Ruff、Python编译和59只fixture端到端验证通过；
- 在线验证失败时保留离线可验证结果，并明确未验证的网络路径。

## 16. 回滚

交易决策层通过单一编排入口接入。回滚时移除`engine.py`对交易决策层的调用，现有评分、Top5、板块2+2、报告前九部分和基础存储继续工作。新增状态文件为追加产物，回滚不删除历史数据；旧消费者忽略新增字段。
