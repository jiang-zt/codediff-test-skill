#!/usr/bin/env python3
"""Fetch GitHub PR or branch-compare diff metadata as structured JSON.

No third-party dependencies. Uses GITHUB_TOKEN when available.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API_ROOT = "https://api.github.com"


def parse_pr_url(url: str) -> Tuple[str, int]:
    match = re.match(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)(?:[/?#].*)?$", url.strip())
    if not match:
        raise ValueError(f"Unsupported GitHub PR URL: {url}")
    return match.group(1), int(match.group(2))


def request_json(url: str, token: Optional[str]) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "codediff-test-skill/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return json.loads(resp.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc


def paged(url: str, token: Optional[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    page = 1
    sep = "&" if "?" in url else "?"
    while True:
        data = request_json(f"{url}{sep}per_page=100&page={page}", token)
        if not isinstance(data, list):
            raise RuntimeError(f"Expected list response from {url}")
        out.extend(data)
        if len(data) < 100:
            break
        page += 1
    return out


def normalize_file(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "path": item.get("filename") or item.get("path"),
        "status": item.get("status"),
        "additions": item.get("additions", 0),
        "deletions": item.get("deletions", 0),
        "changes": item.get("changes", 0),
        "previous_path": item.get("previous_filename"),
        "raw_url": item.get("raw_url"),
        "blob_url": item.get("blob_url"),
        "patch": item.get("patch", ""),
    }


def fetch_pr(repo: str, pr: int, token: Optional[str]) -> Dict[str, Any]:
    pr_url = f"{API_ROOT}/repos/{repo}/pulls/{pr}"
    pr_data = request_json(pr_url, token)
    files_url = f"{API_ROOT}/repos/{repo}/pulls/{pr}/files"
    files = [normalize_file(item) for item in paged(files_url, token)]
    return {
        "source_type": "pull_request",
        "repo": repo,
        "pr_number": pr,
        "title": pr_data.get("title"),
        "html_url": pr_data.get("html_url"),
        "state": pr_data.get("state"),
        "base_ref": pr_data.get("base", {}).get("ref"),
        "head_ref": pr_data.get("head", {}).get("ref"),
        "base_sha": pr_data.get("base", {}).get("sha"),
        "head_sha": pr_data.get("head", {}).get("sha"),
        "files": files,
    }


def fetch_compare(repo: str, base: str, head: str, token: Optional[str]) -> Dict[str, Any]:
    encoded_base = urllib.parse.quote(base, safe="")
    encoded_head = urllib.parse.quote(head, safe="")
    url = f"{API_ROOT}/repos/{repo}/compare/{encoded_base}...{encoded_head}"
    data = request_json(url, token)
    files = [normalize_file(item) for item in data.get("files", [])]
    return {
        "source_type": "compare",
        "repo": repo,
        "base_ref": base,
        "head_ref": head,
        "base_sha": data.get("base_commit", {}).get("sha"),
        "head_sha": data.get("head_commit", {}).get("sha"),
        "status": data.get("status"),
        "ahead_by": data.get("ahead_by"),
        "behind_by": data.get("behind_by"),
        "html_url": data.get("html_url"),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch GitHub PR or compare diff as JSON")
    parser.add_argument("--pr-url", help="GitHub PR URL")
    parser.add_argument("--repo", help="owner/repo")
    parser.add_argument("--pr", type=int, help="Pull request number")
    parser.add_argument("--base", help="Base branch/SHA for compare")
    parser.add_argument("--head", help="Head branch/SHA for compare")
    parser.add_argument("--token", help="GitHub token; defaults to GITHUB_TOKEN")
    parser.add_argument("--output", "-o", default="diff.json", help="Output JSON path")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    try:
        repo = args.repo
        pr = args.pr
        if args.pr_url:
            repo, pr = parse_pr_url(args.pr_url)
        if repo and pr:
            result = fetch_pr(repo, pr, token)
        elif repo and args.base and args.head:
            result = fetch_compare(repo, args.base, args.head, token)
        else:
            parser.error("Provide --pr-url, or --repo + --pr, or --repo + --base + --head")
            return 2
        PathLike = os.PathLike[str]
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Wrote {args.output} with {len(result.get('files', []))} changed files")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should print concise error
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
