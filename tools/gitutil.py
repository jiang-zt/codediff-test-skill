"""Git helpers: diff extraction and disposable worktrees for the parent and child revisions."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from change_models import ChangeContext, ChangedFile

class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root(start: Path) -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    #如果不在任何 git 仓库里，rev-parse 会失败(返回非 0)
    if proc.returncode != 0:
        raise GitError(f"{start} is not inside a git repository. jitcatch tests a change against an earlier "
                       "version, so it needs git: run `git init && git add -A && git commit -m init` first")
    return Path(proc.stdout.strip())


# ------------------------------------------------------------------------- automatic change range

_OWN_FILES = (".jitcatch.toml", "jitcatch.toml", ".jitcatch/")


def has_commits(repo: Path) -> bool:
    return git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False).strip() != ""


def dirty_paths(repo: Path) -> list[str]:
    """Changed or untracked (non-ignored) paths, excluding jitcatch's own files."""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":
            i += 1  # the original path follows a rename/copy entry
        if not path.startswith(_OWN_FILES):
            paths.append(path)
    return paths


def default_branch(repo: Path) -> str | None:
    ref = git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False).strip()
    if ref:
        return ref
    for cand in ("origin/main", "origin/master", "main", "master"):
        if git(repo, "rev-parse", "--verify", "-q", f"{cand}^{{commit}}", check=False).strip():
            return cand
    return None


def snapshot_worktree(repo: Path) -> str:
    """Commit object for the current working tree (tracked changes + untracked, non-ignored files) on top of
    HEAD, created with a throwaway index. No branch, ref, index or file of the user's checkout is touched."""
    with tempfile.TemporaryDirectory(prefix="jcidx-") as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index"),
               "GIT_AUTHOR_NAME": "jitcatch", "GIT_AUTHOR_EMAIL": "jitcatch@localhost",
               "GIT_COMMITTER_NAME": "jitcatch", "GIT_COMMITTER_EMAIL": "jitcatch@localhost"}

        def g(*args: str) -> str:
            proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env)
            if proc.returncode != 0:
                raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
            return proc.stdout.strip()

        g("read-tree", "HEAD")
        g("add", "-A", "--", ".", *(f":(exclude){p.rstrip('/')}" for p in _OWN_FILES))
        tree = g("write-tree")
        return g("commit-tree", tree, "-p", "HEAD", "-m", "Uncommitted changes")


def auto_range(repo: Path) -> tuple[str, str, str]:
    """Pick what to test when no --base/--head is given. Returns (base, head, human description)."""
    if not has_commits(repo):#没有任何 commit → 直接报错
        raise GitError("this repository has no commits yet. jitcatch compares a change against an earlier "
                       "version: commit once (git add -A && git commit -m init), make a change, then run it again")
    if dirty_paths(repo):#有未提交改动 P1
        #用户改了代码还没 commit，直接对比 上一个 commit（HEAD）vs 当前工作区
        # 把当前工作区（含未提交改动）做成一个临时快照，返回一个可被 git 引用的对象
        # 通常是通过 git stash create 生成一个 commit 对象，或 git write-tree + commit-tree 造一个临时 commit）
        # 这样 head 是个真实可 diff 的引用，而 git diff HEAD <snapshot> 就得到"未提交改动"的 diff
        return "HEAD", snapshot_worktree(repo), "your uncommitted changes (compared with the last commit)"
    #用户在 feature 分支上，已经 commit 了一些改动，工作区是干净的 p2   
    head = rev_parse(repo, "HEAD")
    default = default_branch(repo)
    if default and merge_base(repo, rev_parse(repo, default), head) != head:#head 上有 default 没有的提交
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        return default, "HEAD", f"commits on {branch} that are not in {default}"
    # 没有未提交改动、也没在领先默认分支的分支上，但HEAD~1 存在（至少有 2 个 commit)
    # 直接测"最近一次 commit 改了什么"
    if git(repo, "rev-parse", "--verify", "-q", "HEAD~1^{commit}", check=False).strip():
        return "HEAD~1", "HEAD", "the last commit"
    #兜底报错
    raise GitError("only one commit and no uncommitted changes, so there is nothing to compare yet: "
                   "make a change and run jitcatch again")


def ensure_excluded(repo: Path, pattern: str = ".jitcatch/") -> None:
    """Keep jitcatch's output out of `git status` via .git/info/exclude (a local, untracked file)."""
    rel = git(repo, "rev-parse", "--git-path", "info/exclude").strip()
    p = Path(rel) if Path(rel).is_absolute() else repo / rel
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    if pattern not in lines:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(("\n" if lines and lines[-1] else "") + pattern + "\n")


def rev_parse(repo: Path, rev: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()


def merge_base(repo: Path, a: str, b: str) -> str:
    out = git(repo, "merge-base", a, b, check=False).strip()
    return out or a


def show_file(repo: Path, sha: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{sha}:{path}"], cwd=repo, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return proc.stdout if proc.returncode == 0 else None


def commit_messages(repo: Path, base: str, head: str) -> tuple[str, str]:
    """Return (title, description) derived from commits in base..head."""
    out = git(repo, "log", "--format=%s%x1f%b%x1e", f"{base}..{head}", check=False)
    entries = [e.strip() for e in out.split("\x1e") if e.strip()]
    if not entries:
        return "", ""
    subjects, bodies = [], []
    for e in reversed(entries):  # oldest first
        subj, _, body = e.partition("\x1f")
        subjects.append(subj.strip())
        if body.strip():
            bodies.append(body.strip())
    title = subjects[-1] if len(subjects) == 1 else subjects[0]
    desc_parts = []
    if len(subjects) > 1:
        desc_parts.append("Commits:\n" + "\n".join(f"- {s}" for s in subjects))
    desc_parts.extend(bodies)
    return title, "\n\n".join(desc_parts)


def change_context(repo: Path, base: str, head: str, title: str = "", description: str = "") -> ChangeContext:
    head_sha = rev_parse(repo, head)
    base_sha = merge_base(repo, rev_parse(repo, base), head_sha)#得到的是"从分叉点到现在 feature 的净改动"
    if not title and not description:
        title, description = commit_messages(repo, base_sha, head_sha)
    #git diff --name-status -M <base_sha> <head_sha> 得到文件列表状态
    status_out = git(repo, "diff", "--name-status", "-M", base_sha, head_sha)#每个文件只输出"状态码 + 路径"，不含 patch，紧凑。
    numstat_out = git(repo, "diff", "--numstat", "-M", base_sha, head_sha)#git diff --numstat -M <base_sha> <head_sha>
    counts: dict[str, tuple[int, int]] = {}
    for line in numstat_out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            a = int(parts[0]) if parts[0].isdigit() else 0
            r = int(parts[1]) if parts[1].isdigit() else 0
            counts[parts[-1]] = (a, r)
    files: list[ChangedFile] = []
    for line in status_out.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        code = parts[0][0]# 取首字母：M/A/D/R/C/T...
        if code == "R" and len(parts) >= 3:
            old, new = parts[1], parts[2]## 重命名：old, new
        else:
            old = new = parts[-1]# 其它：路径就是最后一个字段
        #git diff -M <base> <head> -- <paths>
        patch = git(repo, "diff", "-M", base_sha, head_sha, "--", *({old, new}))#集合自动去重
        a, r = counts.get(new, counts.get(f"{old} => {new}", (0, 0)))
        #把 status 和 numstat 拼成 ChangedFile，并逐文件取 patch
        files.append(ChangedFile(path=new, old_path=old, status=code, patch=patch, added_lines=a, removed_lines=r))
    full_patch = git(repo, "diff", "-M", base_sha, head_sha)
    return ChangeContext(base_sha=base_sha, head_sha=head_sha, title=title, description=description,
                         files=files, full_patch=full_patch)


@contextmanager
def worktree(repo: Path, sha: str, label: str, link_paths: list[str] | None = None) -> Iterator[Path]:
    """Create a detached worktree at `sha`; symlink heavy dependency dirs from the main checkout."""
    tmp = Path(tempfile.mkdtemp(prefix=f"jcwt-{label}-"))
    wt = tmp / "wt"
    git(repo, "worktree", "add", "--detach", "--force", str(wt), sha)
    try:
        for rel in link_paths or []:
            _link_dependency_dirs(repo, wt, rel)
        yield wt
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
        git(repo, "worktree", "prune", check=False)


def _link_dependency_dirs(repo: Path, wt: Path, name: str) -> None:
    """Symlink every `name` directory (e.g. node_modules) that exists in the main checkout,
    including nested ones in monorepos, unless the worktree already contains it."""
    if "/" in name or os.sep in name:
        candidates = [repo / name]
    else:
        candidates = []
        for dirpath, dirnames, _ in os.walk(repo):
            rel = Path(dirpath).relative_to(repo)
            if rel.parts and rel.parts[0] in (".git", ".jitcatch"):
                dirnames[:] = []
                continue
            if name in dirnames:
                candidates.append(Path(dirpath) / name)
                dirnames.remove(name)  # don't descend into node_modules
            # don't descend into other dependency/build dirs
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv", "venv", "target", "build", "dist")]
    for src in candidates:
        if not src.exists():
            continue
        dst = wt / src.relative_to(repo)
        if dst.exists() or dst.is_symlink():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(src, dst, target_is_directory=src.is_dir())
