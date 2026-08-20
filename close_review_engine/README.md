# 17只A股收盘复盘引擎

固定复盘工业富联、生益科技、华工科技、长电科技、深南电路、光迅科技、沪电股份、世纪华通、北方稀土、兆易创新、兴森科技、北方华创、江海股份、景旺电子、中航光电、鹏鼎控股、世运电路。

## 核心能力

- 先检查沪深交易日和收盘状态，只使用完成日线；
- 日线降级链：东方财富 → 腾讯 → 网易；
- 腾讯15:00快照与60分钟数据交叉验证，必要时才合成当日完成日线；
- 自行计算MA5/10/20/50/100/200、EMA5/10/20/50、RSI14、MACD、KDJ、Stoch RSI、ADX、OBV、ATR、20日高低点与相对20日均量；
- 按30/20/25/15/10权重输出100分综合评分、评级和17只完整排名；
- 输出Top5回踩区、突破触发价、不追价区、失效价、两级目标与风险收益比；
- 保存每日JSON/CSV/Markdown，自动与上一交易日比较；
- 财报、公告或资金流接口失败时只降低对应评分置信度，不取消整份报告。

## 自动执行

默认分支上的 `.github/workflows/a-share-close-review.yml` 使用UTC时间配置，对应北京时间：

- 15:05：首轮收盘数据采集；
- 15:15：补跑；
- 15:30：最终核验并发布/更新当日GitHub Issue。

GitHub计划任务可能因平台负载略有延迟。三轮任务使用同一天“保留更高完整度结果”的机制，避免后一次临时接口故障覆盖前一次完整报告。

## 输出

```text
reports/YYYY-MM-DD.md
data/processed/YYYY-MM-DD/snapshot.json
data/processed/YYYY-MM-DD/ranking.csv
data/state/latest.json
data/state/history.jsonl
```

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
```

真实运行：

```bash
ashare-review run --output-root .
```

这是条件化复盘工具，不是自动交易系统，不承诺收益。
