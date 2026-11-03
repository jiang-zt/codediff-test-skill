# CodeDiff Test MCP

代码变更辅助测试的 stdio MCP 服务。向客户端暴露 `get_code_diff` 和 `submit_test_cases` 两个工具，以及可选的 `analyze_branch_tests` 工作流提示。
客户端模型负责分析和生成用例，本服务负责读取 Git 差异、校验提交参数及向保存用例。


## 调用过程

```text
用户自然语言 + 仓库/base/head
  → 客户端模型选择 get_code_diff tool
  → MCP Server 执行只读 Git 命令
  → 返回固定提交 SHA、变更文件和 patch
  → 客户端模型分析并生成用例草稿
  → submit_test_cases 返回缺参清单或提交预览
  → 用户补齐、审核并确认
  → MCP 保存到本地模拟平台，返回 simulated=true 回执
```

模型运行在支持 MCP 的客户端中，本项目不内置模型、模型密钥或自研 Agent 循环。模型需要完整源代码上下文时，使用客户端另行提供并获准的代码读取能力；本 MCP 不提供源文件读取工具。客户端通过 MCP prompt 获取工作流提示。

## 内容

| 文件 | 职责 |
| --- | --- |
| `tools/local_git_diff.py` | 读取本地已提交分支差异 |
| `mcp_server.py` | 官方 MCP SDK 的 stdio 入口，暴露两个工具及工作流 prompt |
| `prompts/mcp_workflow.md` | 模型如何取 diff、分析、补齐配置和等待确认 |
| `examples/mcp-config.example.json` | 客户端 stdio 配置示例 |
| `examples/sample_cases.json` | 人工编写的模拟提交输入 |
| `tests/` | Git、参数校验、本地 HTTP、真实 MCP stdio 集成测试 |

```text
codediff-test-skill/
├── mcp_server.py
├── requirements.txt
├── README.md
├── tools/
│   └── local_git_diff.py
├── prompts/
│   └── mcp_workflow.md
├── examples/
│   ├── mcp-config.example.json
│   └── sample_cases.json
└── tests/
```

## 安装

需要 Python 3.11+、Git。在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

使用官方 Python SDK `mcp==2.3.0`，不修改全局 Python 环境。

## 连接客户端

参考 `examples/mcp-config.example.json`，将所有 `/绝对路径/...` 替换为实际路径，再添加到客户端的 MCP 配置。

- `command`：本项目 `.venv/bin/python` 的绝对路径。
- `args`：本项目 `mcp_server.py` 的绝对路径。
- `CODEDIFF_ALLOWED_REPOS`：明确允许读取的仓库根目录；多个路径用系统路径分隔符连接（macOS/Linux 为 `:`）。不自动允许其子目录或其他仓库。
- `CODEDIFF_TEST_PLATFORM_URL`：只允许 `http://127.0.0.1:端口`，默认18766。

重新加载客户端后，应看到 `get_code_diff`、`submit_test_cases` 两个工具。不要给写工具配置自动批准；`confirmed` 是调用方的确认声明，并不是服务端对真人身份的认证。

然后发送自然语言，例如：

> 对 `/绝对路径/业务仓库` 的 `feature/example` 相对 `master` 做测试分析。先获取 diff，结合可见代码生成用例；缺少业务信息请列出来，暂不提交。

检查客户端真实工具调用记录，而不是只看模型文字。缺少目标分支时先补充输入。默认 master 不存在时，明确指定实际基准；工具不会静默改成 main。

## CLI 降级与测试

未接入 MCP 时可通过 CLI 直接获取 diff：

```bash
CODEDIFF_ALLOWED_REPOS=/绝对路径/业务仓库 .venv/bin/python tools/local_git_diff.py \
  --repo-path /绝对路径/业务仓库 --base master --head feature/example
```
默认输出标准 JSON，传 `--output` 写入指定文件。

