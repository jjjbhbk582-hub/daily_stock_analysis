# 独立A股历史数据核验

本目录只用于用户授权的一次云端数据验证，不是交易策略或同花顺成品。

## 隔离范围

- 使用独立研究分支，不修改主分支，不调用或修改现有收盘复盘程序。
- 仅在该分支的 `scripts/ashare_research/RUN_DATA_CHECK` 文件发生显式变更时触发新增工作流；无定时运行、无自动重复尝试工作流。
- 使用公开仓库的标准 `ubuntu-24.04` 运行器，单任务上限20分钟；不启用收费大型运行器、不修改付费设置。
- 工作流权限为 `contents: read`，不向仓库回写结果；不读取用户密钥，不调用付费模型或券商，不下单。
- 原始约564MB行情仅在临时运行器中用于当次检查，不提交入库、不上传为产物、不缓存。核验产物最多8MiB，保留7天。

## 固定输入与检查

输入为 `source.json` 固定的公开版本和字节摘要，不自动切换到latest或其他日期。分别下载归档和配套manifest，校验实际文件大小与SHA-256，再核对manifest目标日和实际交易日历。

检查主板代码范围内的open/high/low/close/volume/factor二进制字段，处理日历偏移，输出每只代码在2015-01-01至2026-09-04期间的报价覆盖、缺失、非法价格及字段问题。不会将缺失日自动视为停牌，不会将all.txt的区间自动视为官方上市或退市记录。

## 本地复核

仅需Python 3.10以上的标准库，无需pip安装：

```bash
python3 -m unittest discover -s scripts/ashare_research -p 'test_*.py' -v
python3 scripts/ashare_research/verify_data.py --config scripts/ashare_research/source.json --work-dir /tmp/ashare-data-input --output /tmp/ashare-data-evidence
```

12项本地测试全部使用明确的合成边界输入，不属于真实市场证据。云端必须另行取得并读取固定归档的真实字节。

## 结果解释

- `DATASET_STRUCTURAL_CHECK_PASSED`：取得了指定数据集，限定的结构检查通过；不是官方历史全市场覆盖证明。
- `DATA_RECEIVED_WITH_QUALITY_FLAGS`：已取得数据，但存在需要复核的字段或报价问题；非零退出并保留证据。
- `FAILED`：本次核验未完成；具体失败原因写入结果文件，不生成虚假收益。

产物包括 `report.md`、`result.json`、`mainboard_coverage.csv`（成功读取行情后）、上游manifest和测试记录。未执行回测，没有收益、胜率或可用于实盘的公式。

官方历史市场分母、动态ST/退市状态、公司行为和独立来源准确性仍需后续验证。Qlib复权归一化价格不直接等同于人民币成交价。

本分支不提交合并请求、不合并到主分支。保留分支供复核即可；不再修改触发文件便不会再次运行本新增任务。本文仅为这次中文研究任务新增说明，不修改项目中英主文档或现有应用配置。
