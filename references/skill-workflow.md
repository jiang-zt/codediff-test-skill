# Skill 脚本与取证工作流

## 配置与分发

此仓库根目录即 Skill 包。项目内使用时读取根目录 SKILL.md；要让宿主自动发现，可将包部署到该宿主支持的 Skill 目录，命名为 codediff。至少保留 SKILL.md、scripts/、tools/、references/ 和 prompts/analysis_output.md；只复制 SKILL.md 无法运行。不要分发 .git、.venv、.env、output 或用户会话。此次实现不自动安装到全局。

Python 3.11+ 的标准库即可运行脚本，无需安装 requirements.txt；该文件继续服务于可选 MCP 入口。

- 本地：`CODEDIFF_ALLOWED_REPOS` 配置允许的仓库根目录绝对路径，多个使用系统路径分隔符（macOS/Linux 为 `:`，Windows 为 `;`）。
- GitHub：`CODEDIFF_GITHUB_REPOS` 配置允许的 `owner/repo`，多个用逗号分隔。fork PR 的 head 仓库同样需要明确授权。
- GitHub 私有仓库：在运行进程环境设置 `CODEDIFF_GITHUB_TOKEN`，使用目标仓库只读凭证。不要索要聊天中的令牌，不写入分析 JSON 或追踪文件。无自动 dotenv 加载，不内置凭证。
- 沿用 api.github.com 限制，不支持 GitHub Enterprise 或 GitLab。

以下示例中的绝对路径与 SHA 由本次用户输入、宿主工作区和脚本回执替换。命令参数用安全的参数数组或 shell 引号传递，不把仓库内容拼成可执行命令。

## 1. 固定比较版本

本地 Git，仅比较已提交版本，不包含未提交内容，不执行 fetch/pull/checkout：

```bash
python3 "/绝对路径/codediff/scripts/codediff.py" start-local \
  --repo-path "/授权仓库绝对路径" --base master --head feature/example \
  --session-root "/获准工作目录/会话"
```

GitHub PR：

```bash
python3 "/绝对路径/codediff/scripts/codediff.py" start-github \
  --repo team/service --mode review --pr-number 123 \
  --session-root "/获准工作目录/会话"
```

仅提供提交时使用 `--sha <40位SHA>` 代替编号。候选 PR 或旧 head 返回 `ok=true` 但不是 `status=ready`，不建立会话，需用户选择，不能继续分析。

GitHub 提测：使用 `--mode test --base-sha <40位SHA> --head-sha <40位SHA>`，不混用 PR 参数。分叉基线拒绝比较，不擅自替换基线。

返回 analysis_id、session_dir、diff。检查实际 base/head、head_repo、files、complete/file_list_complete 与 limitations；`complete=true` 不保证 GitHub patch 未截断。

## 2. 补充固定版本完整文件

```bash
python3 "/绝对路径/codediff/scripts/codediff.py" read \
  --session "/返回的会话目录" --side head --path src/service.py
```

- `side` 只能为 head/base，默认 head，不接受任意 SHA 覆盖。fork head 自动从会话的 head_repo 读取，白名单会再次检查。
- 删除文件用 base；重命名旧文件用 base + previous_path。必要时读取相关调用方、测试、配置及旧逻辑。
- 回执 evidence 包含 id、repo、commit_sha、path、side、content、line_count、sha256。content 从第一行开始编号，不能将 patch 的相对位置当作完整文件行号。
- 本地读取真实 Git blob，拒绝目录、子模块、符号链接和非 UTF-8/二进制内容。GitHub Contents API 的符号链接解引用限制仍保留，不能声称校验了链接本身。
- 文件数与内容预算跨会话调用累计；重复读取也计入50份限制。单次 GitHub 请求20秒超时、单响应4MB、单 Reader 累计8MB，沿用已有模块；不是整项任务20秒截止时间。
- 路径未知时明确缺口；不自动扫描全仓库或猜测跨服务关系。文件读取失败会记录安全错误码。

## 3. 检查证据范围

```bash
python3 "/绝对路径/codediff/scripts/codediff.py" status --session "/返回的会话目录"
```

检查 evidence、unread_files、failed_reads、diff_complete 和 saves。GitHub 的 diff_complete 沿用 API 完整性标记；本地模式为 null，表示原本地模块不提供该字段，不表示失败或已证明完整，本地差异超出读取预算会直接报错。unread_files 只检查删除文件的 base 或其他变更的 head 是否读过，不表示旧逻辑、依赖或需求已分析；失败记录保留最近100条。会话为本地 JSON，不是有签名的审计系统。

## 4. 生成分析 JSON 并保存

用宿主文件写入能力生成 UTF-8 JSON，仅允许 report_markdown、test_cases 两个顶层字段。repo/mode/SHA 由会话提供，不能自行传入覆盖。先读取共享报告规范，写入本次真实分析。以下仅为数据形状示例，不是完整交付内容：

```json
{
  "report_markdown": "本次分析结论与风险……代码依据 E0001:L1-L2。未知验收规则待确认，尚未执行测试。",
  "test_cases": [
    {
      "id": "TC-001",
      "name": "实际行为验证名称",
      "priority": "P1",
      "category": "功能",
      "preconditions": ["有依据的版本与状态要求"],
      "test_data": ["真实输入约束与准备方式"],
      "steps": [{"action": "具体操作", "expected": "可观察的断言"}],
      "cleanup": ["有依据的清理方式；只读时说明无需清理"],
      "missing_inputs": ["尚缺的环境或验收规则"],
      "execution_status": "not_executed",
      "evidence": ["E0001:L1-L2"]
    }
  ]
}
```

用例每个 evidence 条目必须完整匹配 `E0001:L1` / `E0001:L1-L2`。正文识别同格式引用并校验；有非空文件证据时正文至少引用一处。脚本不能验证每个自然语言结论与证据语义一致，模型仍需逐项对应。没有完整文件证据时只交付证据不足说明，test_cases=[]。

```bash
python3 "/绝对路径/codediff/scripts/codediff.py" save \
  --session "/返回的会话目录" --input "/获准工作目录/analysis.json" \
  --output-dir "/用户指定报告目录"
```

成功新建独立目录，包含 report.md、test_cases.json、evidence.json。报告自动附加版本证据索引、未读取文件、失败和 diff 完整性限制；evidence.json 含完整 diff 与文件内容，便于本地复核。重试会创建新目录，不覆盖历史，也不提供幂等保存。

`test_cases.json` 的顶层为 schema_version、generated_at、mode、repo、base_sha、head_sha、status=draft、case_count 及 cases（输入的 test_cases 列表）。`evidence.json` 包含会话版本元数据、diff、evidence、failed_reads、unread_files 和完整性说明。共享规范中的“MCP运行机器”在此模式下指运行 Python 脚本的机器；产物路径不是远程下载链接。

会话和文件使用私有权限创建；不改变已存在父目录权限。正常写入异常会清理本次产物；强制终止可能留下未完成文件或 .lock，不能据此声称保存成功。确认没有活跃进程后才能人工清理锁/残留目录。

## JSON 回执与停止条件

所有命令（含 --help）向 stdout 输出一份 JSON；无常规 stderr 输出。`--help` 的 help 字段是帮助文本。

| 退出码 | 含义 |
| --- | --- |
| 0 | 调用成功；start 仍需核对 status=ready，save 仍需核对 status=saved |
| 1 | 操作失败，读取 error.code/message |
| 2 | 参数错误，error.code=INVALID_ARGUMENTS |

认证/授权错误停止并请用户在环境配置；PR_UPDATED 可重启整个比较，不能混用两次会话证据；限流/网络错误最多重试一次，仍失败则列明缺口；SESSION_LIMIT 停止取证并交付部分结果；SESSION_BUSY 不并发重试；INVALID_EVIDENCE 先修正引用，不跳过校验。已有底层错误码原样返回，意外输入或文件错误返回不包含内部异常详情的 INVALID_INPUT_OR_IO。
