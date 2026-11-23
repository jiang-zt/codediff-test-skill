#!/usr/bin/env python3
"""Read committed local Git tree differences without checkout, pull or external diff drivers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from dataclasses import asdict
from change_models import ChangeContext, ChangedFile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gitutil import commit_messages, rev_parse,auto_range,GitError,git
diff_args = (
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "-M",
)

def read_changed_files(
    repo: Path,
    base_sha: str,
    head_sha: str,
) -> list[tuple[str, str, str]]:
    """返回 (状态码, 旧路径, 新路径) 列表。"""
    status_out = git(repo,"diff","--no-ext-diff","--no-textconv","--no-color","-M","--name-status","-z",base_sha,head_sha,"--",)

    files: list[tuple[str, str, str]] = []
    parts = status_out.split("\0")
    index = 0

    while index < len(parts):
        status = parts[index]
        index += 1

        if not status:
            continue

        code = status[0]
        old = new = parts[index]
        index += 1

        if code in ("R", "C"):
            new = parts[index]
            index += 1

        files.append((code, old, new))

    return files


def read_numstat(
    repo: Path,
    base_sha: str,
    head_sha: str,
) -> dict[str, tuple[int, int]]:
    """返回 {新路径: (新增行数, 删除行数)}。二进制文件记为 (0, 0)。"""
    numstat_out = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-M", "--numstat", "-z", base_sha, head_sha, "--")

    counts: dict[str, tuple[int, int]] = {}
    parts = numstat_out.split("\0")
    index = 0

    while index < len(parts):
        entry = parts[index]
        index += 1

        if not entry:
            continue

        added, removed, path = entry.split("\t", 2)

        # 重命名/复制：统计项后紧跟旧路径、新路径。
        if path == "":
            path = parts[index + 1]
            index += 2

        counts[path] = (
            int(added) if added.isdigit() else 0,
            int(removed) if removed.isdigit() else 0,
        )

    return counts

def read_patch(
    repo: Path,
    base_sha: str,
    head_sha: str,
    *,
    paths: list[str] | None = None,
) -> str:
    """读取完整 patch，或指定文件的 patch。"""
    if paths is not None and not paths:
        raise ValueError("paths 不能为空列表；获取完整 diff 请使用 None")

    # 保持路径顺序并去重，按字面路径匹配。
    pathspecs = (
        [f":(literal){path}" for path in dict.fromkeys(paths)]
        if paths is not None
        else []
    )

    return git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-M", base_sha, head_sha, "--", *pathspecs)

"""
get_local_diff(repo_path, base=None, head=None)
    │
    ├─ base、head 都提供
    │    → 使用指定的 base 和 head
    │
    ├─ 只提供 base
    │    → head 使用当前 HEAD
    │
    ├─ 只提供 head
    │    → base 使用 head 的第一父提交
    │    → 如果 head 是根提交，则报错：不存在父提交
    └─ base、head 都没提供
         │
         ├─ 有未提交修改（含未忽略的新文件）
         │    → base = 当前 HEAD
         │    → head = 工作区快照提交
         │
         ├─ 工作区干净，当前分支相对默认分支有新提交
         │    → base = 当前 HEAD 与默认分支的共同祖先
         │    → head = 当前 HEAD
         │
         ├─ 否则，存在上一个提交
         │    → base = HEAD~1
         │    → head = 当前 HEAD
         │
         └─ 无可比较版本
              → 报错，说明原因
    ↓
解析并固定最终 base_sha、head_sha
    ↓
获取 diff、文件状态、增删行数、提交说明
    ↓
构造 ChangedFile 列表
    ↓
返回保存 ChangeContext(
    base_sha,
    head_sha,
    title,
    description,
    files,
    full_patch,
)
"""

def get_local_diff(repo_path: str, base: str | None = None, head: str | None = None,) -> ChangeContext:
     
    # 1. 根据输入确定比较范围。
    if base is not None and head is not None:
        base_sha = rev_parse(repo_path, base)
        head_sha = rev_parse(repo_path, head)
    elif base is not None:
        base_sha = rev_parse(repo_path, base)
        head_sha = rev_parse(repo_path, "HEAD")

    elif head is not None:
        head_sha = rev_parse(repo_path, head)
        # 从固定后的 SHA 找第一父提交，不重新解析原始引用。
        try:
            base_sha = rev_parse(repo_path, f"{head_sha}^1")
        except GitError as exc:
            raise GitError(
                f"无法获取 {head_sha} 的第一父提交；"
                "请检查该提交是否为根提交或仓库历史是否完整"
            ) from exc
    else:
        base_sha, head_sha,what = auto_range(repo_path)

    # 2. 从固定版本提取提交说明。
    title, description = commit_messages(repo_path, base_sha, head_sha)

     # 3. 提取文件状态和增删统计。
    # 这两个函数应复用现有的 -z 解析逻辑，支持特殊文件名。
    entries = read_changed_files(repo_path, base_sha, head_sha)
    counts = read_numstat(repo_path, base_sha, head_sha)

    files: list[ChangedFile] = []
    for code, old, new in entries:
        paths = [new] if old == new else [old, new]
        patch = git(
            repo_path,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "-M",
            base_sha,
            head_sha,
            "--",
            *(f":(literal){path}" for path in paths),
        )
        added, removed = counts.get(new, (0, 0))

        files.append(
            ChangedFile(
                path=new,
                old_path=old,
                status=code,
                patch=patch,
                added_lines=added,
                removed_lines=removed,
            )
        )
    # 4. 单独读取完整 patch，不拼接逐文件结果。
    full_patch = read_patch(repo_path, base_sha, head_sha)

    return ChangeContext(
        base_sha=base_sha,
        head_sha=head_sha,
        title=title,
        description=description,
        files=files,
        full_patch=full_patch,
    )



def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-path',required=False)
    parser.add_argument('--base', default=None)
    parser.add_argument('--head',default=None)
    parser.add_argument('--output','-o',default="diff/change_context.json")
    args=parser.parse_args()
    try:
        result=get_local_diff(args.repo_path,args.base,args.head)
        text = json.dumps(asdict(result), ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text+'\n',encoding='utf-8')
        else:
            print(text)
        return 0
    except (OSError) as error:
        print(json.dumps({'ok':False,'error':{'code':getattr(error,'code','IO_ERROR'),'message':str(error)}},ensure_ascii=False),file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
