# ChatGPT定时任务衔接提示词

GitHub数据引擎合并到默认分支并通过一次真实运行后，可将ChatGPT定时任务改为以下读取规则：

```text
每个沪深A股交易日北京时间15:30执行。

读取GitHub仓库 jjjbhbk582-hub/daily_stock_analysis 默认分支中的：
close_review_engine/reports/YYYY-MM-DD.md
必要时核对：
close_review_engine/data/processed/YYYY-MM-DD/snapshot.json

YYYY-MM-DD必须为北京时间当天日期。

1. 当天休市时，只回复“今日A股休市，不进行重新排名”。
2. 当日报告存在时，完整转述报告，不得用上一交易日报告冒充。
3. 当日报告尚未生成时，检查“17只A股收盘复盘”工作流和当日Issue，说明正在运行或明确具体失败来源。
4. 行情、技术指标、评分、Top5和关键价位以当日snapshot.json为结构化真源。
5. 可补充巨潮资讯、上交所和深交所的当日新公告，但不得覆盖已验证行情字段。
6. 不承诺收益，不写成确定性交易指令。
```

本文件不代表ChatGPT Scheduled Task已自动修改；该任务需要在支持任务编辑的ChatGPT界面中单独更新。
