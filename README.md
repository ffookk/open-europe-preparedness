# Open Europe Preparedness

欧洲安全与民防准备开放数据库项目。

本项目计划整理欧洲各国与欧盟公开的国防、民防和应急准备政策，帮助读者区分网络主张、原始证据、法律状态、实施进度和长期目标，并建立可以通过 Pull Request 持续纠错的协作流程。

## 当前状态

已实现第一版政策记录 JSON Schema、[字段与证据审阅规范](docs/record-format.md)、Python 标准库校验 CLI 及回归测试。政策阶段与核查结果分别保存，检查日期、跨文件唯一 ID、来源定位以及已核查记录的必需字段。

**当前有 3 条经 AI 代理原始来源复核的真实记录、2 条待核查来源线索，以及 1 条 synthetic 虚构格式示例。** 本轮于2026年9月20日读取欧盟官方原文，分别记录非立法战略的通过、72小时自给指引的制定计划，以及 rescEU 能源储备已有部署的官方陈述。`verified` 表示来源支持精确主张，**这3条尚未完成人工审阅，不构成人工认证**；[来源复核记录](docs/source-review.md)列明方法、证据位置和边界。网站和查询工具尚未实现。合成示例的 `verified` 状态仅演示字段完整性。

## 本地运行

需要 Python 3.10 或更高版本，无需安装第三方依赖。以下命令不联网：

```sh
python3 scripts/validate_records.py data/verified.json data/pending.json examples/synthetic.json
python3 -m unittest discover -s tests -v
```

校验 CLI 接受一个或多个 JSON 文件，并在所有输入间检查重复 ID。运行 `python3 scripts/validate_records.py --help` 可查看参数说明。退出码 `0` 表示命令成功（显示帮助或结构检查通过），`1` 表示数据或文件错误，`2` 表示命令行参数错误。**通过检查不代表政策事实已经核实。** 真实核查仍需阅读原始资料、定位证据，并经过人工 PR 审阅。

| 内容 | 位置 |
|---|---|
| 机器可读数据结构 | [`schema/policy-records.schema.json`](schema/policy-records.schema.json) |
| 字段、状态和证据审阅规则 | [`docs/record-format.md`](docs/record-format.md) |
| 3 条经代理来源复核的真实记录 | [`data/verified.json`](data/verified.json) |
| 来源位置、方法与核查边界 | [`docs/source-review.md`](docs/source-review.md) |
| 2 条待核查研究线索 | [`data/pending.json`](data/pending.json) |
| 1 条完全虚构的完整示例 | [`examples/synthetic.json`](examples/synthetic.json) |
| 标准库校验命令 | [`scripts/validate_records.py`](scripts/validate_records.py) |

## 项目目标

- 为可独立核查的政策主张建立结构化记录。
- 分开记录提议、通过、生效、实施中和目标完成等政策阶段。
- 整理官方民防指南索引与注明出处的中文摘要。
- 支持资料补充、状态更新、事实纠错、翻译和代码贡献。

初期关注预备役与征兵制度、国际条约状态、公开防御与庇护设施政策，以及家庭应急准备建议。记录应明确适用国家、人群、时间和统计口径。

## 核查原则

一条记录只回答一个可以独立核查的问题。例如，预备役年龄上限调整与未来预备役人数目标应分别记录。

**政策阶段和核查结论必须分开。** 一个提案可以被确认确实存在，但仍未通过或生效；人数目标也不等于当前规模。宣布、通过、生效和目标日期不能互相替代。

优先使用政府、议会、法律数据库、国际组织和官方指南。每条记录应提供来源链接、发布机构、发布日期及相关条款、段落或页码，并说明证据支持的具体内容和限制。

尚未审阅来源的线索应标为待核查，最后核查日期留空。链接失效或无法访问只表示需要复查，不能据此判定政策虚假。自动检查仅验证数据结构与一致性；事实判断仍需人工审阅证据。

## 初期工作与验收标准

1. **定义数据格式与状态规则。** 建立 schema、字段说明和格式示例，明确未知日期、待核查线索、政策阶段与核查结论的表示方式。
2. **完成首批政策核查。** 将芬兰预备役年龄与规模目标拆开，分别整理有关国家退出《渥太华公约》的时间线，并核对欧盟家庭应急准备建议。
3. **建立贡献与验证流程。** 添加记录检查程序和 CI，检查必填字段、日期及重复编号，并保留人工证据审阅步骤。
4. **整理指南索引。** 提供官方原文链接、语言和版本信息，摘要清楚标注来源与适用范围。

第一阶段验收标准：收录 **10 条可独立核查的政策记录**，每条具备来源、政策阶段、核查结论、关键日期、适用范围和最后核查日期；一位首次参与者能够依照贡献说明完成一次纠错 PR。

## 官方来源索引与剩余线索

欧盟 Preparedness 与 rescEU 已完成下述有限范围的代理来源复核，具体记录见上表；其余链接仍是筹备期线索，未验证可访问性或政策事实。

| 研究方向 | 来源线索 | 后续核查重点 |
|---|---|---|
| 芬兰预备役制度 | [芬兰政府：预备役年龄上限](https://valtioneuvosto.fi/en/-/236553176/finland-to-raise-reservist-age-limit-to-65-years-as-of-2026) | 法律依据、适用人群、生效日期与人数目标口径 |
| 杀伤人员地雷条约 | [联合国条约登记](https://treaties.un.org/Pages/ViewDetails.aspx?chapter=26&clang=_en&mtdsg_no=XXVI-5&src=TREATY) | 逐国核对通知日期、生效日期和声明 |
| 欧盟应急准备 | [欧盟委员会：Preparedness](https://commission.europa.eu/topics/preparedness_en) | 已复核战略通过与72小时指引计划；后续指引发布和各国要求待查 |
| 欧盟应急储备 | [欧盟委员会：rescEU](https://civil-protection-humanitarian-aid.ec.europa.eu/what/civil-protection/resceu_en) | 已复核能源储备部署陈述；其他能力与数量待查 |
| 瑞典民防指南 | [官方手册 PDF](https://rib.msb.se/filer/pdf/30874.pdf) | 版本、发布日期及摘要对应页码 |

## 参与方式

阅读 [贡献说明](CONTRIBUTING.md) 和 [路线图](ROADMAP.md)，再提出资料线索或聚焦单一问题的修改。PR 应说明改了什么、依据是什么、尚有哪些不确定性。没有编程经验也可以贡献来源、纠错和翻译。

第三方网页、出版物和原文继续适用各自的版权及使用条件；收录外链不代表重新授权。项目原创内容的许可安排须以仓库实际提供的许可证为准。
