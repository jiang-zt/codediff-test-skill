# CodeDiff Skill

CodeDiff 是由模型驱动的代码变更测试分析与评审 Skill。获取本地 Git 分支／提交之间的 diff、远程 GitHub PR diff，或远程两个提交之间的 diff，结合固定版本源码分析变更影响、测试风险和回归范围，生成中文测试分析报告与未执行的测试用例草稿。

## 支持的分析场景

| 场景 | 输入 | CLI 入口 |
| --- | --- | --- |
| 本地分支／提交 diff | 已授权的仓库路径、明确的 base/head 分支名或提交引用 | `start-local` |
| 远程 GitHub PR diff | 已授权的 owner/repo、PR 编号或关联 PR 的完整 SHA | `start-github --mode review` |
| 远程 GitHub 提交 diff | 已授权的 owner/repo、base/head 的 40 位完整 SHA | `start-github --mode test` |

本地分支名在启动时解析为固定 SHA，仅分析已提交内容，不包含工作区未提交改动，也不自动 fetch、pull 或 checkout。远程提交比较要求 base 为 head 的祖先，目前不直接接受远程分支名；PR 输入有歧义或指定 SHA 不是当前 PR head 时，不自动切换版本。

对话请求示例（路径、仓库和版本需替换为实际值）：

- 本地分支：“分析本地仓库 `/绝对路径/业务仓库` 中 `feature/example` 相对 `main` 的变更，给出测试风险、回归范围和用例草稿，保存到 `/绝对路径/报告目录`。”
- 远程 PR：“对 `https://github.com/OWNER/REPO/pull/123` 做测试影响分析，读取必要源码，将报告与用例草稿保存到 `/绝对路径/报告目录`。”
- 远程提交：“对 `OWNER/REPO` 的 base `<40位完整SHA>` 到 head `<40位完整SHA>` 做测试分析，保存到 `/绝对路径/报告目录`。”

## 入口与执行

- [SKILL.md](SKILL.md)： Skill 的入口，定义角色、流程和约束。
- [prompts/skill-workflow.md](prompts/skill-workflow.md)：入口引用的 CLI 参数、配置、回执和停止条件。
- [prompts/analysis_output.md](prompts/analysis_output.md)：报告与用例规范。

需要 Python 3.11+，脚本仅使用标准库；本地 Git 模式还需要 Git。配置仓库授权与 GitHub 凭证的方法见执行工作流。凭证通过进程环境配置，不在对话中提供。

```bash
python3 /绝对路径/Codediff/tools/codediff.py --help
```

执行顺序：`start-local` / `start-github` → `read` → `status` → `save`。所有后续操作绑定 start 返回的会话，使用固定版本证据。同一会话串行操作。

## 文件目录与架构

```text
Codediff/
├── SKILL.md                      入口：角色、工作流程与约束
├── README.md                     使用说明与架构
├── prompts/
│   ├── skill-workflow.md         CLI 参数、配置、回执与停止条件
│   └── analysis_output.md        测试分析报告与用例规范
└── tools/
    ├── codediff.py               CLI 入口：start / read / status / save
    ├── evidence_session.py       会话管理、版本绑定、证据编号与引用校验
    ├── local_git_diff.py         本地 Git diff 与固定提交文件读取
    ├── github_reader.py          GitHub PR／提交 diff 与文件读取
    ├── change_symbols.py         变更行与 Python 符号定位
    └── analysis_artifacts.py     报告与用例校验、格式化和保存
```

模型负责选择要读取的文件、理解证据及撰写测试分析；CLI 负责固定版本取数、管理证据和保存产物。分发时保留以上入口、资源及 Python 模块，不分发本地凭证、会话和生成产物。项目仅保留 Skill CLI 链路。

## 证据与交付

模型根据 diff 风险读取完整变更文件和已知依赖；路径未知时明确缺口，不自动构建调用图。Python 符号定位用于辅助理解变更归属，不证明调用关系。

每份文件证据记录固定 SHA、路径、完整内容、行数与 SHA256，报告和用例通过 `E0001:L1-L5` 格式引用。保存前校验引用及范围，不验证模型自然语言推论是否正确。

保存目录由用户明确指定；成功保存后返回 `report.md`、`test_cases.json`、`evidence.json` 的路径。证据包含源码，仅保存在本机获准目录。用例为未执行草稿，不执行测试、部署或回写 PR。

## 入口检查

```bash
python3 tools/codediff.py --help
```

此命令只检查 CLI 帮助入口，不代表业务测试已执行。
