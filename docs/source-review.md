# 首批官方来源复核记录

复核日期：2026年9月20日。此次由 AI 代理实际读取下列官方网页与 PDF，核对文档编号、日期、章节和具体表述；没有使用旧聊天回答作为证据。未进行独立人工认证、实地调查或交付审计。`data/verified.json` 中的 `verified` 表示所列证据支持当前精确主张，人工审阅完成数仍为0。

## 本次三个独立主张

| 记录 | 精确范围与状态 | 原始证据位置 |
|---|---|---|
| `eu-preparedness-union-strategy-adoption` | 非立法战略于2025年3月26日通过；`adopted` 只描述该战略文件 | [委员会实施追踪器](https://commission.europa.eu/priorities-2024-2029/security-and-defence/implementation-tracker_en) 的 Non-legislative items → Adopted → 对应日期条目；[联合通报](https://commission.europa.eu/document/download/526806b6-c4e1-43d1-81b7-947308efbab1_en?filename=Joint+Communication.pdf)封面，JOIN(2025) 130 final |
| `eu-population-self-sufficiency-guidelines-plan` | 2025年文件宣布将提出最低72小时自给指引；`announced` 对应这一制定计划 | 同一联合通报第3节、关键行动14，印刷页10（PDF第11页）；[行动计划附件](https://commission.europa.eu/document/download/755117bc-10ac-4549-a438-9767cf8f19d1_en?filename=Placeholder+Annex.pdf)印刷页3（PDF第4页）第28行 |
| `eu-resceu-energy-generator-deployments` | 主管机构报告能源储备已向乌克兰部署数千台发电机；`implementing` 对应已有执行证据 | [rescEU 项目页](https://civil-protection-humanitarian-aid.ec.europa.eu/what/civil-protection/resceu_en)的 Energy 小节最后一段 |

## 日期和解释边界

- 战略通报和附件封面均为2025年3月26日。[Preparedness 页面](https://commission.europa.eu/topics/preparedness_en)的下载列表对两个文件另有3月24日和25日标签；记录采用实际文件封面日期，并以实施追踪器核对战略通过日。
- 附件将指引安排写为2026这一指示性年份，没有月日。当前 schema 只允许完整年月日，因此 `target_at` 留空，年份保留在主张和来源说明中。目标年份不证明完成，也不应被人为补成12月31日。
- 72小时记录限定为2025年原文中的计划。此次未系统核查之后的指引发布情况、欧盟后续立法或成员国规定，不能从这条历史记录回答某国现行家庭义务。
- rescEU 页脚显示最后更新于2026年8月11日，首发日与部署日期未明确，故 `published_at` 和政策日期留空。页面动态变化，没有逐台交付清单；“数千台”是官方陈述而非独立审计结果。同页承办国数量在不同段落有差异，本次没有采用这些数字。
- 通过战略文件、宣布制定指引、已经部署设备是不同层次的事实；任何一条都不支持预测战争时间或声称全部准备项目完成。

## 线索迁移与后续复核

原 `eu-household-preparedness-lead` 已拆为战略通过和指引计划两条，旧线索的历史保留在指引记录的 `change_history` 中。芬兰预备役年龄与联合国条约登记线索仍在 `data/pending.json`，本轮未访问或升级它们的核查状态。

下一位审阅者可以按上表直接打开来源，逐项复核主张、定位、日期、政策阶段和局限，再通过 PR 记录人工审阅结果或纠错。若扩大主张到当前实施进度，应查找新的官方证据并更新适用时间；不应只改状态标签。库内只保存中文概述与公开来源链接，不复制网页全文，不包含私人对话、家庭资料或账户信息。

本地结构检查覆盖所有真实数据和合成示例，跨文件检查ID唯一性；测试不联网，也不能证明政策事实正确：

```sh
python3 scripts/validate_records.py data/verified.json data/pending.json examples/synthetic.json
python3 -m unittest discover -s tests -v
python3 scripts/privacy_check.py --history
```
