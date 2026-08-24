# ChatGPT定时任务衔接提示词

GitHub板块2+2数据引擎合并到默认分支并通过一次真实运行后，可将ChatGPT定时任务改为以下读取规则：

```text
每个沪深A股交易日北京时间15:35执行。

读取GitHub仓库 jjjbhbk582-hub/daily_stock_analysis 默认分支中的：
close_review_engine/reports/YYYY-MM-DD.md
必要时核对：
close_review_engine/data/processed/YYYY-MM-DD/snapshot.json
close_review_engine/data/processed/YYYY-MM-DD/ranking.csv
close_review_engine/data/state/latest.json

YYYY-MM-DD必须为北京时间当天日期。

1. 先确认当天是否为沪深A股交易日。休市时只回复“今日A股休市，不进行重新排名”。
2. 必须核对snapshot.json中的target_date等于北京时间当天、schema_version=2、valid_count=59、universe_count=59。
3. 当日报告存在且校验通过时，完整转述报告，不得使用上一交易日报告冒充。
4. 报告必须保留十一部分：市场环境；行业板块完整排名；重点概念板块；强势/上升/退潮板块；重点板块2+2；59只固定股票完整排名；固定池Top5；动态候选买点；与上一次比较；推荐交易计划；最终操作结论。推荐交易计划必须列明主推荐、备选、回踩区、突破触发价、禁止追高价、止损价、两档止盈、风险收益比和仓位纪律；无合格机会时明确写空仓观察。
5. 板块2+2中的动态候选必须满足沪深主板、当日有效收盘价不高于100元、非ST、成交额不少于3亿元。某角色没有合格标的时原样保留空缺，不强行补足。
6. 固定59只股票池与动态板块候选池必须分开。动态候选不会自动永久加入固定池。
7. 行情、技术指标、板块评分、固定Top5和动态候选关键价位均以当日snapshot.json为结构化真源。
8. 当日报告尚未生成时，检查“A股板块2+2与固定池收盘复盘”工作流和当日通知，说明仍在运行或明确具体失败来源；不得把单个接口失败描述成整个A股市场没有数据。
9. 可以补充巨潮资讯、上交所和深交所的当日新公告，但不得覆盖已验证行情字段。
10. 不承诺收益，不写成确定性交易指令，明确区分“股票本身优秀”“当前价格值得买”“目前只适合观察”。
```

本文件不代表ChatGPT Scheduled Task已自动修改；该任务需要在支持任务编辑的ChatGPT界面中单独更新。
