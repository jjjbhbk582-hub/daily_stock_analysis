# A股板块2+2与固定股票池收盘复盘引擎

系统固定监控59只沪深A股（完整名单见`config/universe.yml`），同时增加全市场板块排名和动态2+2候选。

## 核心能力

### 固定59只股票池

- 先检查沪深交易日和收盘状态，只使用完成日线；
- 日线降级链：东方财富 → 腾讯 → 网易；
- 腾讯15:00快照与60分钟数据交叉验证，必要时才合成当日完成日线；
- 自行计算MA5/10/20/50/100/200、EMA5/10/20/50、RSI14、MACD、KDJ、Stoch RSI、ADX、OBV、ATR、20日高低点与相对20日均量；
- 按30/20/25/15/10权重输出100分综合评分、评级、59只完整排名和固定池Top5；
- 输出回踩区、突破触发价、不追价区、失效价、两级目标与风险收益比。

### 交易决策与计划追踪

- 保留100分综合评分，同时新增剔除基本面占位分的技术交易评分；
- 基本面分为`verified/partial/missing/stale`，缺失或过期不会直接屏蔽短线技术机会，但会醒目标记并把单股模型仓位上限降至7.5%；
- 回踩和突破使用独立入场、止损、两档目标、赔率和追高线，突破第一目标严格高于突破入场；
- 只有行情高置信度、技术评分至少70、日线多头、60分钟非空头、第一目标赔率至少1.8且无硬风险时才进入交易候选；没有合格标的时允许空仓；
- 动作状态分为`ready_next_session`、`waiting_trigger`、`watch_only`、`rejected`，等待触发不等于可以立即买入；
- 模型按每笔账户风险0.5%计算仓位，市场状态限制组合总仓位为70%/50%/30%，单行业不超过25%；没有用户真实持仓时仅表示模型上限；
- 活动计划遵守A股T+1、跳空取消、目标1减半、保护止损和最长5个交易日；同日止损/止盈顺序不明时标记`ambiguous`并排除统计；
- 滚动统计只使用当时真实保存的计划，样本少于30笔时明确显示统计置信度不足。

### 板块全景与2+2

- 分开输出行业板块完整排名和概念板块排名；
- 板块100分模型：当日及相对强度20、5日/20日趋势20、成交额与相对量能20、板块广度与涨停15、龙头和梯队15、催化/风险代理10；
- 每日选择强势板块Top5、排名提升最快Top2和退潮风险Top3；
- 对去重后的重点板块（最多7个）选择：资金容量龙头、弹性龙头、缩量回踩潜力、放量突破潜力；
- 固定跟踪AI算力、CPO、PCB、半导体、存储芯片、稀土、人形机器人、创新药、液冷服务器、消费电子、军工和有色金属；
- 动态候选不写入固定59只股票池，只对当日和下一交易日有效。

## 动态候选硬过滤

所有2+2股票必须同时满足：

- 仅沪市主板或深市主板普通A股，代码前缀为`600/601/603/605/000/001/002/003`；
- 目标日收盘价大于0且不高于100元；
- 排除ST、*ST、退市风险、停牌、一字涨跌停；
- 当日成交额不少于3亿元、成交量大于0；
- 同一板块四个角色不得重复；不足四只合格股票时明确空缺，不强行补足。

参数位于`config/sector_monitor.yml`。其中100元、沪深主板、非ST和3亿元流动性门槛属于硬约束。

## 数据与容错

- 板块列表、板块历史K线和板块成份优先使用东方财富公开接口；
- 板块列表读取源时间戳，日期与目标交易日不符时直接拒绝，不把当前数据冒充历史数据；
- 单个板块或概念接口失败不会中止固定59只股票复盘；
- 概念数据缺失时明确标记，不使用固定59只样本冒充全市场概念板块；
- 财报、公告、资金流或板块扩展字段失败时只降低对应置信度。

## 报告结构

正式Markdown报告包含十一部分：

1. 市场环境；
2. 行业板块完整排名；
3. 重点概念板块；
4. 强势、上升与退潮板块；
5. 重点板块2+2；
6. 59只固定股票完整排名；
7. 固定池Top5重点分析；
8. 动态候选买点；
9. 与上一次排名对比；
10. 推荐交易计划（市场状态、今日可执行、等待触发、基本面缺失标记、观察/回避、回踩与突破双计划、逐股趋势/量价/基本面/板块/赔率分析依据、昨日验收和滚动统计）；
11. 最终操作结论。

## 自动执行

默认分支上的`.github/workflows/a-share-close-review.yml`对应北京时间：

- 15:05：首轮收盘数据采集；
- 15:15：补跑；
- 15:30：最终核验并发布/更新当日通知。

GitHub计划任务可能因平台负载略有延迟。同一天多次运行会优先保留固定池和板块层完整度更高的结果。

## 输出

```text
reports/YYYY-MM-DD.md
data/processed/YYYY-MM-DD/snapshot.json
data/processed/YYYY-MM-DD/ranking.csv
data/state/latest.json
data/state/history.jsonl
data/state/trade_plans.json
data/state/trade_outcomes.jsonl
```

`snapshot.json`使用schema v2，新增`sectors`，包含行业/概念排名、固定关注概念、重点板块、2+2角色、动态候选、板块比较和来源状态。

同一快照追加`trade_decision`、`previous_trade_review`和`trade_statistics`。活动计划保存在`trade_plans.json`；已结束结果以不可变JSONL记录在`trade_outcomes.jsonl`，不会用今天的算法倒推历史信号。

## 本地验收

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .

ashare-review run \
  --as-of 2026-08-20 \
  --force \
  --fixture config/review_fixture.yml \
  --output-root /tmp/a-share-review
python scripts/verify_outputs.py /tmp/a-share-review 2026-08-20
ashare-review evaluate-trades --output-root /tmp/a-share-review
```

真实运行：

```bash
ashare-review run --output-root .
```

板块联网烟雾测试：

```bash
python scripts/run_sector_live_smoke.py --as-of YYYY-MM-DD --workers 8
```

这是条件化复盘工具，不是自动交易系统，不承诺收益，也不把板块龙头等同于当前价格值得买。
