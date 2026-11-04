# CodeDiff Test MCP

提供「获取 GitHub PR」、「 提测版本 diff」、「获取对应版本的完整代码」功能给AI调用, 辅助测试进行评审或测试影响分析。测试人员无需 clone 或准备本地仓库。分析完成后可自动保存Markdown报告和JSON用例草稿。建议在IDE(VS Code、IDEA、Cursor等)中进行配置使用。

## 工具

| 工具 | 输入 | 用途 |
| --- | --- | --- |
| `get_review_diff` | `repo`、`pr_number` 或 `sha` | 获取 PR 变更；SHA 无唯一 PR 时返回候选，旧 SHA 不会静默替换为最新版本 |
| `get_test_diff` | `repo`、`base_sha`、`head_sha` | 获取基线到提测版本差异；基线必须为提测版本祖先 |
| `read_github_file` | `repo`、`commit_sha`、`path` | 获取指定提交的完整 UTF-8 文本文件，不超过 1MB |
| `save_analysis_report` | `mode`、`repo`、`base_sha`、`head_sha`、`report_markdown`、`output_dir`、可选 `test_cases` | 将模型分析保存为本地报告和用例草稿 |
| `get_code_diff` | `repo_path`、`head`、可选 `base` | 本地 Git 两个提交树比较；默认 base=master |

`repo` 格式为 `OWNER/REPO`，所有 GitHub SHA 参数要求 **40 位完整 SHA**。用户提供 PR 链接时，由 AI 提取仓库和编号。仅 SHA 无法确定仓库，需提供仓库或明确配置的唯一仓库。

模型负责分析和生成用例，MCP负责提供证据并保存本地文件；不内置模型、不执行静态扫描或测试、不回写PR，暂不接入CI门禁。

## 安装与配置

需要 Python 3.11+；仅使用本地 Git 功能时才需要 Git。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

MCP SDK `mcp==2.3.0`。参考 `examples/mcp-config.example.json` 添加到 IDE 的 MCP 配置，替换 Python 和脚本绝对路径：

- `CODEDIFF_GITHUB_REPOS`：允许读取的仓库，例如 `team/service,team/shared`。fork PR 的 head 仓库也需列入，按需明确授权。
- `CODEDIFF_GITHUB_TOKEN`：本机配置 GitHub 只读凭证。Fine-grained token 选择目标仓库，授予 **Contents: Read** 和 **Pull requests: Read**。公共仓库可留空；私有仓库需要有权限的凭证，组织策略可能要求额外批准。
- `CODEDIFF_ALLOWED_REPOS`：使用本地功能时需要；多个绝对路径用系统路径分隔符连接（macOS/Linux 为 `:`）。

配置示例只有占位符，必须替换或删除令牌占位符。配置后重启/重新加载 MCP，检查出现上述工具。四个证据工具为只读，`save_analysis_report` 只在用户对话中指定的目录下新建文件。客户端可能对该写入工具显示权限提示。

## IDE 对话示例

PR 评审：

> 评审 https://github.com/OWNER/REPO/pull/123。调用 get_review_diff，再用 read_github_file 读取完整变更方法和必要依赖，输出带代码证据的缺陷与风险，将报告和用例草稿保存到 `/Users/你的用户名/测试报告`，返回文件路径。

仅有开发给的 SHA：

> 评审 OWNER/REPO 中提交 <40位SHA> 关联的 PR；如果多个 PR 或不是最新 head，先告诉我，不自动更换版本。

提测分析：

> 对 OWNER/REPO 做提测分析，base_sha=<上次已测版本40位SHA>，head_sha=<本次提测40位SHA>。先取 diff，再读取对应版本完整代码，给出影响范围、回归重点和测试用例草稿，将报告和用例保存到 `/Users/你的用户名/测试报告` 并返回文件路径。

客户端支持 MCP prompts 时，可调用 `analyze_github_changes`（mode=`review`/`test`）。完整流程见 `prompts/github_workflow.md`。服务器工具描述也包含基本选路与上下文要求；仅注册 MCP 不保证所有 IDE 模型严格遵循提示，需查看真实工具调用记录。

## 自动生成的文件

保存目录由用户在对话中给出，例如“保存到 `/Users/你的用户名/测试报告`”。`output_dir` 必填，接受绝对路径或 `~/测试报告`，没有默认目录，不再读取 `CODEDIFF_OUTPUT_DIR`。用户未提供目录时，模型先询问；分析可以继续，保存需等到目录明确。

模型完成分析后，在用户指定目录下生成：

```text
用户指定的保存目录/
└── test-20261104T080000Z-随机后缀/
    ├── report.md
    └── test_cases.json
```

- `report.md`：仓库、实际比较SHA、UTC时间、模型分析及可阅读的用例步骤和预期结果。
- `test_cases.json`：版本与生成信息、`status=draft`、用例数量及结构化用例列表。每条用例要求 `name`、`steps[{action,expected}]`、非空 `evidence`，可选 `priority=P0/P1/P2`。没有可靠用例时保存空列表。
- 工具会创建尚不存在的目录，并在其中为每次调用创建独立子目录，不覆盖历史记录；重试会创建新目录。报告与用例输入总计不超过2MB，最多500条用例，每条最多100步。
- 返回绝对 `report_path`、`test_cases_path` 和 `case_count`。文件在MCP运行的机器上；远程客户端需自行获取文件，这不是文件下载接口。
- MCP不内置模型；“自动”依赖客户端模型遵循服务器指令/工作流，在分析后真实调用保存工具。用户要求仅对话输出时跳过；仅返回 `ok=true,status=saved` 才能声称已生成文件。
- 内容仍为模型分析和测试草稿，不代表评审通过或测试已执行。写入失败返回错误并清理本次不完整目录，已保存的历史目录不受影响。

## 版本与完整性

- PR 使用共同祖先到 head 的差异，返回 `target_base_sha`、`comparison_base_sha`、`head_sha` 和 `head_repo`。读取前后核对 PR 版本，更新则报错重试。
- 提测使用 GitHub compare；只有基线是 head 祖先时才接受，确保符合版本端点比较。分叉时返回 `DIVERGED_BASE`，不擅自改变基线。
- PR 文件列表分页读取，并核对数量；compare 文件列表达到300个时保守标记不完整。缺少 patch 时 `complete=false`。
- `complete=true` 只表示列表完整且 patch 字段存在，**不保证 GitHub patch 未截断，也不代表模型分析完整**。模型须读取完整文件，明确未覆盖范围。
- 删除文件读 `comparison_base_sha`；重命名旧文件读 `previous_path`。fork PR 的 head 文件用 `head_repo` 读取，仍受仓库白名单限制。
- 每次工具调用有20秒请求超时、单响应4MB、累计8MB预算。只访问 `https://api.github.com`，不跟随重定向或外部下载链接。不支持 GitHub Enterprise 自定义域名或 GitLab MR。
- Contents API可能解引用仓库内符号链接；文件工具的 `complete` 只说明返回文本完整，不保证是请求路径的原始 Git blob。符号链接本身的变更需另行核对。
- 不提供全仓库搜索或完整调用链分析。模型按已知路径读取相关接口、测试和配置；路径未知或跨服务依赖缺失时需补充材料，不能猜测。

## 本地能力

`get_code_diff` 只读取允许的本地仓库，比较两个已提交树，不包含未提交内容，不自动 fetch/pull/checkout。

```bash
CODEDIFF_ALLOWED_REPOS=/绝对路径/业务仓库 .venv/bin/python tools/local_git_diff.py \
  --repo-path /绝对路径/业务仓库 --base master --head feature/example
```

本地分析 prompt 为 `analyze_branch_tests`。

## 文件与验证

- `tools/github_reader.py`：GitHub 只读获取、校验和错误处理。
- `tools/analysis_artifacts.py`：报告与测试草稿校验、本地独立目录写入。
- `tools/local_git_diff.py`：原有本地 Git 读取。
- `mcp_server.py`：stdio MCP 工具和 prompts。
- `prompts/github_workflow.md`：远程评审与提测工作流。

验证命令：

```bash
.venv/bin/python -m unittest discover -s tests -v
```
