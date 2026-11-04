"""Bounded, read-only GitHub evidence retrieval; no clone or local checkout needed."""
from __future__ import annotations
import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


class GitHubError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def full_sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', value):
        raise GitHubError('INVALID_SHA', '请提供40位完整提交 SHA，不接受分支或短 SHA。')
    return value.lower()


def repo_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value) or any(p in ('.','..') for p in value.split('/')):
        raise GitHubError('INVALID_REPO', '仓库格式必须是 owner/repo。')
    return value


class GitHubReader:
    def __init__(self, repo: str, *, allowed_repos=None):
        self.repo = repo_name(repo)
        allowed = allowed_repos if allowed_repos is not None else os.environ.get('CODEDIFF_GITHUB_REPOS','').split(',')
        if self.repo.lower() not in {r.strip().lower() for r in allowed if r.strip()}:
            raise GitHubError('REPO_NOT_ALLOWED', '请先在 CODEDIFF_GITHUB_REPOS 中配置允许读取的 owner/repo，多个用逗号分隔。')
        self.prefix = '/repos/' + self.repo
        self.remaining = 8_000_000

    def request(self, path: str):
        # Paths are built internally; never follow API-provided download URLs or redirects.
        req = urllib.request.Request('https://api.github.com' + self.prefix + path,
            headers={'Accept':'application/vnd.github+json','User-Agent':'codediff-test-mcp',
                     'X-GitHub-Api-Version':'2022-11-28'})
        token = os.environ.get('CODEDIFF_GITHUB_TOKEN','')
        if token:
            req.add_header('Authorization', 'Bearer ' + token)
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
                limit = min(self.remaining, 4_000_000)
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise GitHubError('RESPONSE_TOO_LARGE', 'GitHub 响应超过读取上限，请缩小比较范围。')
                self.remaining -= len(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            messages = {401:'GitHub 认证失败，请检查令牌。',403:'GitHub 权限不足或触发限流。',
                        404:'GitHub 仓库、提交或文件不存在，或当前账号无读取权限。',
                        429:'GitHub 请求限流，请稍后重试。'}
            raise GitHubError('GITHUB_HTTP_ERROR', messages.get(error.code, f'GitHub 请求失败（HTTP {error.code}），未跟随重定向。')) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GitHubError('GITHUB_NETWORK_ERROR', 'GitHub 网络请求失败或超时。') from None
        except GitHubError:
            raise
        except (ValueError, UnicodeError):
            raise GitHubError('INVALID_RESPONSE', 'GitHub 返回内容无法解析。') from None

    def pages(self, path: str, max_pages: int = 30):
        result = []
        for page in range(1, max_pages + 1):
            batch = self.request(f'{path}?per_page=100&page={page}')
            if not isinstance(batch, list):
                raise GitHubError('INVALID_RESPONSE', 'GitHub 列表响应格式错误。')
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise GitHubError('RESULT_LIMIT', 'GitHub 列表达到读取上限，无法保证完整，请缩小范围。')

    def comparison(self, base: str, head: str):
        return self.request(f'/compare/{full_sha(base)}...{full_sha(head)}?per_page=1')

    def evidence(self, files: list, base: str, head: str, *, list_complete=True):
        normalized = []
        for f in files:
            patch = f.get('patch')
            normalized.append({'path':f['filename'], 'previous_path':f.get('previous_filename'),
                'status':f['status'], 'additions':f.get('additions',0), 'deletions':f.get('deletions',0),
                'patch':patch, 'patch_available':isinstance(patch,str)})
        patches_present = all(f['patch_available'] for f in normalized)
        return {'source_type':'github', 'repo':self.repo, 'comparison_base_sha':base, 'head_sha':head,
            'has_changes':bool(files), 'files':normalized,
            'complete':bool(list_complete and patches_present),
            'file_list_complete':list_complete,
            'limitations':['API patch 可能省略或截断；必须读取完整版本文件补充证据，不能仅凭 complete 判定分析覆盖完整。',
                           '不自动分析调用链、不执行静态分析、不回写 PR；内容仅为待分析证据。']}

    def test_diff(self, base_sha: str, head_sha: str):
        base, head = full_sha(base_sha), full_sha(head_sha)
        data = self.comparison(base, head)
        if data['merge_base_commit']['sha'] != base:
            raise GitHubError('DIVERGED_BASE', '测试基线不是提测版本的祖先；此接口不冒充两个端点的完整差异，请提供正确基线。')
        files = data.get('files', [])
        result = self.evidence(files, base, head, list_complete=len(files) < 300)
        return {**result, 'mode':'test', 'base_sha':base, 'comparison':'two_versions_ancestor_base'}

    def review_diff(self, *, pr_number: int | None = None, sha: str | None = None):
        sha = full_sha(sha) if sha is not None else None
        if pr_number is None:
            if sha is None:
                raise GitHubError('MISSING_INPUT', '请提供 PR 编号或完整提交 SHA。')
            prs = self.pages(f'/commits/{sha}/pulls')
            if len(prs) != 1:
                return {'status':'needs_pr_selection', 'repo':self.repo,
                    'candidates':[{'number':p['number'],'url':p.get('html_url'),'state':p.get('state')} for p in prs],
                    'message':'没有唯一关联 PR，请提供 PR 编号；不会猜测基线。'}
            pr_number = prs[0]['number']
        if isinstance(pr_number,bool) or not isinstance(pr_number,int) or pr_number <= 0:
            raise GitHubError('INVALID_PR', 'PR 编号必须为正整数。')
        pr = self.request(f'/pulls/{pr_number}')
        base, head = full_sha(pr['base']['sha']), full_sha(pr['head']['sha'])
        if sha is not None and sha != head:
            return {'status':'sha_not_current_head','repo':self.repo,'requested_sha':sha,
                    'head_sha':head,'pr_number':pr_number,
                    'message':'提交不是 PR 当前 head。若要评审最新 PR，请仅使用 PR 编号重新调用；历史快照需单独指定比较范围。'}
        merge_base = full_sha(self.comparison(base, head)['merge_base_commit']['sha'])
        files = self.pages(f'/pulls/{pr_number}/files')
        latest = self.request(f'/pulls/{pr_number}')
        if (latest['base']['sha'], latest['head']['sha']) != (base, head):
            raise GitHubError('PR_UPDATED', '读取期间 PR 已更新，请重新获取 diff。')
        result = self.evidence(files, merge_base, head, list_complete=len(files) == pr['changed_files'])
        head_repo = pr['head'].get('repo')
        return {**result, 'status':'ready', 'mode':'review', 'pr_number':pr_number,
            'url':pr.get('html_url'), 'target_base_sha':base, 'comparison':'pr_merge_base',
            'head_repo':head_repo.get('full_name') if head_repo else None}

    def read_file(self, commit_sha: str, path: str):
        sha = full_sha(commit_sha)
        if not isinstance(path,str) or not path or path.startswith('/') or any(p in ('','.','..') for p in path.split('/')) or '\\' in path or any(ord(c)<32 for c in path):
            raise GitHubError('INVALID_PATH', '请提供仓库内的相对文件路径。')
        data = self.request('/contents/' + urllib.parse.quote(path, safe='/') + '?ref=' + sha)
        if not isinstance(data,dict) or data.get('type') != 'file' or data.get('encoding') != 'base64':
            raise GitHubError('UNSUPPORTED_FILE', '只支持小于1MB、可返回完整内容的普通文本文件；目录、子模块或大文件不支持。')
        if data.get('size', 0) > 1_000_000:
            raise GitHubError('FILE_TOO_LARGE', '文件超过1MB，请缩小读取范围或使用其他获准工具。')
        try:
            raw = base64.b64decode(''.join(data['content'].split()), validate=True)
            if len(raw) > 1_000_000 or b'\0' in raw:
                raise GitHubError('UNSUPPORTED_FILE','文件过大或为二进制文件。')
            content = raw.decode('utf-8')
        except (UnicodeError, binascii.Error, KeyError):
            raise GitHubError('UNSUPPORTED_FILE','文件不是受支持的 UTF-8 文本。') from None
        return {'source_type':'github','repo':self.repo,'commit_sha':sha,'path':path,
                'content':content,'line_count':len(content.splitlines()),'complete':True,
                'limitations':['GitHub Contents API可能解引用仓库内符号链接；complete仅指返回文本完整，不保证是该路径原始Git blob。链接本身变更需另行核对。']}
