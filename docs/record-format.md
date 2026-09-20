# 政策记录 v1：字段和证据审阅规则

机器可读结构见 [`schema/policy-records.schema.json`](../schema/policy-records.schema.json)。标准库 CLI 是本仓库提交检查的执行入口：它额外检查真实日历日期、跨文件 ID 唯一性、来源网址、最后核查日期与来源访问日期的关系。JSON Schema 校验器通常需要另行启用 `format` 检查，也不能代替跨文件或事实审查。

每个 JSON 文件顶层仅包含 `schema_version: 1` 和非空的 `records` 数组。记录不接受额外字段。UTF-8 JSON 不允许重复键或 NaN/Infinity。`null` 表示未知或尚未发生；禁止用空字符串、零日期或猜测日期占位。

`schema_version` 必须写成整数 `1`；字符串 `"1"`、浮点数 `1.0` 和布尔值 `true` 均不被 CLI 接受。
允许 `null` 的字段仍必须保留键名；“值未知”和“缺少字段”是两种不同情况。
枚举值区分大小写；例如使用 `verified`，不能写成 `Verified` 或中文标签。

| 字段 | 含义与规则 |
|---|---|
| `id` | 全部输入文件中唯一的英文小写 slug。合成记录使用 `synthetic-` 前缀，真实研究记录禁止使用该前缀。 |
| `record_type` | `real` 是关于现实政策的研究记录，可能仍待核查；`synthetic` 是完全虚构的格式示例。 |
| `jurisdiction` | 国家、欧盟或条约登记范围。避免把欧盟建议自动写成某成员国法律。 |
| `topic` | `reserve_service`、`treaty_status`、`civil_protection`、`household_preparedness`、`emergency_stockpiles`、`other`。 |
| `title` / `claim` | 标题及一个可独立核查的准确表述。待核查线索可写明确的研究问题；完整真实记录须聚焦单个主张。 |
| `scope` | 适用人群、国家、时间或统计口径。不要加入个人姓名、家庭地址或账户信息。 |
| `policy_stage` | 政策进程，见下表。 |
| `verification_status` | 对当前主张的核查结果，见下表。 |
| `dates` | 固定含 `announced_at`、`adopted_at`、`effective_at`、`target_at`；每项为 `YYYY-MM-DD` 或 `null`。目标日期可以在未来。 |
| `sources` | 至少一个来源，字段见下一节。 |
| `last_verified_at` | 最近一次证据审阅日期；`pending` 必须为 `null`，其他核查结果必须有有效日期且不得在未来。 |
| `verification_note` | 当前核查方法、结论及边界。格式检查通过不能写成已人工核实。 |
| `limitations` | 非空字符串数组，明确证据局限；不能用空白内容充数。 |
| `change_history` | 至少一个 `{ "date": "YYYY-MM-DD", "summary": "…" }` 条目；记录结论更正和重要状态变化，不记录贡献者私人信息。 |

## 两种状态彼此独立

| 政策阶段 | 含义 |
|---|---|
| `unknown` | 还没有足够证据确定阶段。 |
| `announced` | 已宣布意向；不据此推定形成正式提案。 |
| `proposed` | 已形成可确认的提案或草案。 |
| `adopted` | 有关程序已正式通过；不自动等于生效。 |
| `in_force` | 有明确依据证明已生效。 |
| `implementing` | 有证据证明正在实际执行。 |
| `completed` | 已证实完成记录所描述的具体事项。 |
| `withdrawn` | 所记录的提案或措施已撤回。条约退出须依据具体主张描述，不能仅凭此标签代替法律生效时间线。 |

| 核查结果 | 含义 |
|---|---|
| `pending` | 尚未完成证据审阅。 |
| `verified` | 阅读原始证据后，判断其支持当前精确表述；审阅者类型和边界须在 verification_note 写明。 |
| `disputed` | 已审阅证据与当前主张存在冲突，需要解释。 |
| `outdated` | 已确认原记录或证据不再反映当前状态；说明适用时间。 |
| `inconclusive` | 已尝试核查，但证据不足以确定结论。 |

例如，`proposed + verified` 表示“确实存在该提案”，不表示已经通过。`unknown + verified` 也可能用于确认某个事实、但尚无法把政策归入后续阶段。状态间不存在自动推进规则。

`verified` 不表示政府背书、独立审计或人工认证。人工和 AI 代理的来源审阅均须明确记录审阅方式；代理审阅不得写成已人工确认。第一阶段的人工审阅验收门槛保留。

未阅读来源的全新线索使用 `policy_stage: "unknown"`、`verification_status: "pending"` 和 `last_verified_at: null`。这是编辑规则；CLI 不会自动从核查状态推导政策阶段。无法访问链接也不能自动判为 `disputed` 或把某项政策判为虚假。

## 来源字段

每项来源固定包含以下字段：

- `url`：HTTPS 原始来源链接，无用户信息、密码、明显凭据查询字段、空白或非标准端口；禁止 localhost、本地域名和 IP 地址字面量。域名末尾的 DNS 点会先移除再检查，不能据此绕过本地地址、IP 或保留域名限制。官方来源的普通查询参数可以保留。优先公开政府、议会、法律数据库和国际组织页面；人工检查并清除私人分享码、令牌、登录链接和跟踪参数，CLI 不具备完整隐私识别能力。
- `publisher` / `title`：发布机构和文档标题；未审阅线索必须明确标题仅是线索标签。
- `published_at`：原文发布日期；未知时为 `null`，不要用访问日代替。
- `locator`：条文号、页码、章节或可稳定定位的段落；未找到时为 `null`。
- `accessed_at`：实际访问日期；未访问时为 `null`。不得写未来日期，也不得晚于该记录的最后核查日期。
- `supports`：用自己的话概述该位置具体支持什么，以及不能推出什么；未阅读时为 `null`。避免复制整段受版权保护内容。

标为 `verified` 时，每个来源的 `locator`、`accessed_at`、`supports` 都必须完整；未审阅的延伸阅读线索应留在独立 `pending` 记录。其他核查结果可保留缺失的来源定位，以便表达无法核实的实际情况，但必须给出审查日期和说明。

## 合成示例、真实数据和运行检查

`examples/synthetic.json` 只有 1 条虚构示例。它用 `verified` 演示完整字段，所写访问日、核查日、机构和支持内容均为虚构。来源仅允许 `example.org` 或 `example.invalid`，不计入真实记录或已核验政策数量。`data/verified.json` 有3条完成代理来源复核的真实记录，方法和范围见 [来源复核记录](source-review.md)。`data/pending.json` 保留2条来自既有 README 的待核查线索，其中条约索引仍需逐国拆分。待核查线索、合成示例和未经人工审阅的记录均不计入第一阶段10条人工审阅政策记录目标。

```sh
python3 scripts/validate_records.py data/verified.json data/pending.json examples/synthetic.json
python3 -m unittest discover -s tests -v
```

需要 Python 3.10 或更高版本，仅用标准库；不联网、不安装依赖，也不抓取来源页面。退出码 `0` 为结构检查通过，`1` 为文件或记录错误，`2` 为命令用法错误。校验结果仅使用 `input-1`、`input-2` 等输入序号、字段位置和规则，不输出路径、文件名或原始字段值。

完成真实核查时，先阅读原始证据并保留稳定位置，再写精确主张、适用范围、各项日期、限制及更正记录，最后运行校验并提交 PR 供人工复核。一个完整且通过校验的 JSON 文件仍然可能包含错误事实；机器检查不能取代人工判断。
