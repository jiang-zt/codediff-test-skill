---
name: codediff-test-skill
description: "面向 Java/Spring 项目的 GitHub PR 测试影响分析 skill。用于从 PR diff 或分支对比出发，结合本地项目代码阅读 Controller、Service、DTO、Mapper、配置和依赖变更，生成中文 Markdown 测试影响分析报告、接口测试用例建议、回归范围和可选 Postman 资产。"
version: "0.1.0"
user-invocable: true
argument-hint: "[GitHub PR URL | repo+PR 编号 | repo+base+head | 本地 Java 项目路径]"
allowed-tools: Read, Grep, Glob, Bash, WebFetch, Write
---

# 代码变更测试影响分析 Skill

本 skill 用于分析 **Java/Spring 项目** 的 **GitHub PR diff**，并结合本地项目代码生成面向测试人员的中文交付物：

- PR 测试影响分析报告
- 受影响接口与接口测试用例建议
- P0/P1/P2 回归范围
- 数据库、配置、依赖、兼容性风险
- 可选 Postman 集合

如果用户提供 PRD、需求文档或接口文档，也应将其作为可选上下文和证据来源参与分析。未提供文档时，继续基于 diff 和本地代码分析，并在报告中说明分析边界。

默认只读分析目标业务仓库。除非用户明确要求，不修改业务代码、不新增测试代码、不调整项目结构。

## 触发场景

当用户要求以下任务时使用本 skill：

- 分析 GitHub PR 的测试影响
- 根据代码 diff 生成测试用例或回归范围
- 从 Java/Spring 变更中识别受影响接口
- 为 PR 变更生成中文测试影响分析报告
- 可选生成 Postman、pytest、JMeter、YAML 等测试资产草稿
- 结合 PRD、需求文档或接口文档分析测试点、验收标准和接口契约影响

## 输入形式

优先使用 GitHub PR 输入，也支持分支对比：

```text
https://github.com/{owner}/{repo}/pull/{number}
repo={owner}/{repo}, pr={number}
repo={owner}/{repo}, base={target_branch}, head={source_branch_or_sha}
```

强烈建议同时提供本地项目路径：

```text
local_repo=/path/to/java-spring-project
```

可选提供产品、需求或接口文档：

```text
prd=/path/to/prd.md
requirements=https://...
api_doc=/path/to/openapi.yaml
interface_doc=/path/to/interface.docx
```

如果有本地项目代码，必须优先结合完整代码上下文分析；如果只有 GitHub patch，只能做保守分析，并在报告中标明局限。

如果提供了 PRD、需求文档或接口文档，必须在测试建议和回归范围中对齐业务目标、验收标准、接口契约、字段约束和异常场景；如果未提供，报告中说明“未提供需求/接口文档，业务验收标准仅能从代码和 diff 推断”。

## 资源分层

本 skill 的文件职责必须保持清晰：

- `SKILL.md`：规定总流程、触发条件、输入输出、边界检查和交付约束。
- `prompts/`：描述每个流程步骤的具体执行说明。
- `tools/`：提供某一步可能用到的脚本工具，例如拉取 diff、初步分析 Java/Spring 变更、生成报告或 Postman。
- `examples/`：提供样例输入，仅用于验证链路。

不要把具体脚本实现细节写进 `SKILL.md`；需要执行某一步时再读取对应 prompt。

## 总流程

1. **输入确认**
   - 读取 `prompts/intake.md`。
   - 明确 PR 来源、本地项目路径、输出类型、测试环境提示和已知高风险模块。
   - 输出分析前提和缺失信息。

2. **拉取结构化 diff**
   - 读取 `prompts/github_pr_diff_collect.md`。
   - 使用 `tools/github_pr_diff.py` 拉取 GitHub PR 或分支对比信息。
   - 如果在用户项目根目录运行，默认将 `diff.json` 放到 `diff/<featureID>/` 子目录。

3. **可选读取需求与接口文档**
   - 如果用户提供 PRD、需求文档、接口文档或 OpenAPI/Swagger，读取 `prompts/requirement_context_analysis.md`。
   - 提取业务目标、功能点、用户角色、接口契约、字段约束、验收标准、异常场景和测试关注点。
   - 如果未提供文档，记录为分析边界，不阻塞后续流程。

4. **结合本地项目代码分析影响面**
   - 读取 `prompts/java_spring_impact_analysis.md`。
   - 先用 `diff.json` 确定变更文件和 patch。
   - 如果有本地项目路径，必须回读完整 Controller、Service、DTO、Mapper、配置、依赖和已有测试代码。
   - 如果有需求或接口文档，将代码影响面与文档中的业务规则、验收标准和接口契约对齐。
   - 默认将 `impact.json` 放到 `output/<featureID>/`，作为后续报告和测试资产的统一证据底稿。

5. **生成接口测试建议**
   - 读取 `prompts/api_testcase_builder.md`。
   - 基于 `impact.json` 中的 API、DTO、Service、Mapper 风险，以及可选文档中的验收标准和接口契约，生成中文测试用例建议。

6. **生成回归范围**
   - 读取 `prompts/regression_scope.md`。
   - 按 P0/P1/P2 输出业务回归范围，并说明纳入或排除的依据。

7. **生成中文 Markdown 报告**
   - 读取 `prompts/report_builder.md`。
   - 使用 `tools/report_builder.py` 或 agent 直接整理输出中文测试影响分析报告。

8. **可选生成测试资产**
   - 如用户要求且识别到接口，读取 `prompts/postman_collection_builder.md`。
   - 使用 `tools/postman_builder.py` 生成 Postman 集合草稿。

9. **阶段性 harness 检查与交付自检**
   - 每个关键阶段结束后执行边界点检查。
   - 交付前读取 `prompts/self_check.md`。
   - 发现证据不足、范围不清或不确定项缺失时，先修正报告或明确说明限制。

## 项目根目录落盘规则

如果 skill 在用户的 Java/Spring 项目根目录运行，默认在该项目根目录下创建：

```text
项目根目录/
├── diff/
│   └── <featureID>/
│       └── diff.json
└── output/
    └── <featureID>/
        ├── impact.json
        ├── test-impact-report.md
        └── postman_collection.json
```

`diff/<featureID>/` 放本次拉取的 diff 文件；`output/<featureID>/` 放本次 diff 的分析产物。

`featureID` 命名规则：

1. 优先从 PR 的 head 分支名提取最后一段，例如 `feature/JIRA-123-login` 取 `JIRA-123-login`。
2. 如果没有 head 分支，使用当前本地日期时间生成，例如 `analysis-20260529-114530`。
3. 如果没有 head 分支但有 PR 编号，可为了可追溯性使用 `pr-<number>-20260529-114530`。
4. 文件夹名必须安全化：将 `/`、空格和不适合作为路径的特殊字符替换为 `-`。

执行工具前应确保目录存在：

```bash
mkdir -p "diff/<featureID>" "output/<featureID>"
```

如果用户指定输出目录，以用户指定目录为准；否则使用上述项目根目录规则。

## 工具映射

| 流程步骤 | 可用工具 |
|---|---|
| 拉取 PR 或分支对比 diff | `python3 tools/github_pr_diff.py ...` |
| 分析 Java/Spring 变更 | `python3 tools/java_spring_analyzer.py --diff-json diff/<featureID>/diff.json --repo-root . --output output/<featureID>/impact.json` |
| 生成中文 Markdown 报告 | `python3 tools/report_builder.py --impact-json output/<featureID>/impact.json --output output/<featureID>/test-impact-report.md` |
| 生成可选 Postman 集合 | `python3 tools/postman_builder.py --impact-json output/<featureID>/impact.json --output output/<featureID>/postman_collection.json` |

## 报告必须包含

中文 Markdown 报告至少包含：

1. PR 基本信息
2. 分析范围与前提
3. 需求 / 接口文档依据
4. 变更摘要
5. 变更文件分类
6. 本地代码上下文阅读结果
7. 受影响接口
8. 接口测试用例建议
9. 业务回归范围
10. 数据库 / 配置 / 依赖风险
11. 建议补充的自动化测试
12. 不确定项与人工确认项
13. 测试结论建议

## 证据规则

- 每个受影响接口、测试建议和回归范围都应引用文件路径、方法名、接口路径或 diff 来源。
- 不得编造接口、字段、业务规则、鉴权方式或数据含义。
- PRD、需求文档、接口文档是可选证据源；未提供时不得假设存在文档结论。
- 文档和代码不一致时，应列入“不确定项与人工确认项”，并分别引用代码证据和文档证据。
- 静态分析无法确认时，必须写入“不确定项与人工确认项”。
- 如果只基于 patch、没有本地项目上下文，报告必须降低结论强度。
- 对 Java/Spring 项目，优先关注 `@RestController`、`@RequestMapping`、`@GetMapping`、`@PostMapping`、DTO 校验注解、MyBatis XML、Repository、Service、配置文件和依赖文件。

## Harness（关卡检查）

这里的 harness 是指每个流程阶段结束前的“关卡检查”，用于防止分析链路带着错误继续往下走。MVP 阶段可先用 prompt 清单执行，不必新增脚本；后续可以扩展为 `tools/harness_validate.py`。

必须检查的关卡：

```text
□ 输入关卡：PR/base/head、本地项目路径、输出目标已确认或已记录缺失
□ 文档关卡：如提供 PRD/需求/接口文档，已读取并提取测试相关信息；如未提供，已记录分析边界
□ 目录关卡：项目根目录下已创建 diff/<featureID>/ 与 output/<featureID>/
□ Diff 关卡：diff/<featureID>/diff.json 已生成，包含 repo、base/head 或 PR 编号、变更文件列表
□ 上下文关卡：如存在本地项目路径，已读取变更相关完整代码文件
□ 影响面关卡：Controller、Service、DTO、Mapper、配置、依赖、测试变更未被跳过
□ 证据关卡：重要结论均能回指文件、方法、接口或 diff
□ 报告关卡：报告为中文，P0/P1/P2 清晰，不确定项单独列出
□ 资产关卡：Postman 等资产只包含已识别或用户确认的接口
```

## Agent 行为约束

- 默认只读分析，不修改业务仓库。
- 若需要生成报告、JSON 或 Postman 文件，应先确认用户允许落盘，或用户已明确要求生成。
- 若用户要求“直接分析并生成”，可以按项目根目录下的 `diff/<featureID>/` 和 `output/<featureID>/` 落盘。
- 若 GitHub API、权限或本地项目路径不可用，应说明阻塞点并给出可继续的最小输入。
- 所有面向用户的报告和说明默认使用中文。
