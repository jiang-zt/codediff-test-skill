# GitHub Diff 拉取

## 目标

从 GitHub PR 或分支对比中拉取结构化 diff，生成 `diff.json`。该文件是后续本地代码阅读、影响面分析和测试报告的证据入口。

## 输出位置

如果在用户项目根目录运行，推荐将 diff 文件放到：

```text
diff/<featureID>/diff.json
```

如果用户指定目录，以用户指定目录为准。

执行拉取前先创建目录：

```bash
mkdir -p "diff/<featureID>"
```

## 推荐工具

PR URL：

```bash
python3 tools/github_pr_diff.py \
  --pr-url "https://github.com/owner/repo/pull/123" \
  --output diff/<featureID>/diff.json
```

repo + PR 编号：

```bash
python3 tools/github_pr_diff.py \
  --repo owner/repo \
  --pr 123 \
  --output diff/<featureID>/diff.json
```

repo + base/head：

```bash
python3 tools/github_pr_diff.py \
  --repo owner/repo \
  --base main \
  --head feature/foo \
  --output diff/<featureID>/diff.json
```

私有仓库优先使用环境变量：

```bash
GITHUB_TOKEN=... python3 tools/github_pr_diff.py ...
```

或显式传入：

```bash
python3 tools/github_pr_diff.py ... --token "$GITHUB_TOKEN"
```

## 期望 JSON

`diff.json` 至少应包含：

```json
{
  "source_type": "pull_request",
  "repo": "owner/repo",
  "pr_number": 123,
  "base_ref": "main",
  "head_ref": "feature/foo",
  "base_sha": "...",
  "head_sha": "...",
  "files": [
    {
      "path": "src/main/java/com/example/UserController.java",
      "status": "modified",
      "additions": 12,
      "deletions": 3,
      "changes": 15,
      "patch": "@@ ..."
    }
  ]
}
```

## Diff 关卡 Harness（关卡检查）

拉取后检查：

```text
□ diff.json 文件存在且 JSON 可解析
□ diff.json 位于用户项目根目录的 diff/<featureID>/ 下，除非用户指定了其他目录
□ featureID 已记录；无 head 分支时已用当前日期时间兜底
□ 包含 repo、PR 编号或 base/head
□ files 不为空
□ 每个 file 至少有 path、status、patch 或变更统计
□ patch 缺失或过大时已记录为后续不确定项
```

## 失败处理

- GitHub API 权限失败：记录 HTTP 状态和错误信息，要求用户提供 token 或仓库访问权限。
- base/head 不完整：暂停 diff 拉取，要求补充 base 和 head。
- patch 不足以判断 Java 上下文：继续下一步时必须优先使用本地项目路径读取完整代码。
