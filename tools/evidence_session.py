"""Local, sequential evidence sessions for the Skill CLI; no model or MCP dependency."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from tools.analysis_artifacts import save_analysis, _validate, _write_text
from tools.github_reader import GitHubError, GitHubReader, full_sha
from tools.local_git_diff import DiffError, get_local_diff, read_local_file

MAX_SESSION_BYTES = 20_000_000
MAX_FILES = 50
MAX_CONTENT_BYTES = 8_000_000
CITATION = re.compile(r'E[0-9]{4}:L[0-9]+(?:-L[0-9]+)?')
REPORT_REFERENCE = re.compile(r'(?<![A-Za-z0-9_])E[0-9]+:[A-Za-z0-9_-]+')


class SessionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def absolute_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SessionError('INVALID_PATH', '请提供绝对目录路径。')
    return path.resolve()


def read_json(path, limit=MAX_SESSION_BYTES):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise SessionError('INPUT_TOO_LARGE', 'JSON 文件超过读取上限。')
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError, RecursionError):
        raise SessionError('INVALID_INPUT', '文件不是有效的 UTF-8 JSON。') from None


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def write_manifest(directory, state):
    raw = json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    if len(raw.encode('utf-8')) > MAX_SESSION_BYTES:
        raise SessionError('SESSION_LIMIT', '会话文件超过大小上限，请缩小分析范围。')
    descriptor, name = tempfile.mkstemp(prefix='.session-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(raw)
        os.replace(name, Path(directory) / 'session.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked_session(directory):
    directory = absolute_path(directory)
    lock = directory / '.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SessionError('SESSION_BUSY', '会话正在使用；若进程已终止，确认后移除会话中的 .lock 再重试。') from None
    try:
        os.close(descriptor)
        state = read_json(directory / 'session.json')
        if not isinstance(state, dict) or state.get('schema_version') != 1:
            raise SessionError('INVALID_SESSION', '不支持的会话格式。')
        yield directory, state
    finally:
        lock.unlink()


def start_session(source, session_root, **parameters):
    root = absolute_path(session_root)
    if source == 'local_git':
        diff = get_local_diff(parameters['repo_path'], parameters['base'], parameters['head'])
        mode = 'test'
    else:
        mode = parameters['mode']
        reader = GitHubReader(parameters['repo'])
        if mode == 'review':
            diff = reader.review_diff(pr_number=parameters.get('pr_number'), sha=parameters.get('sha'))
            if diff.get('status') != 'ready':
                return diff  # No session is created for ambiguous or stale PRs.
        else:
            diff = reader.test_diff(parameters['base_sha'], parameters['head_sha'])
    state = {'schema_version': 1, 'analysis_id': uuid.uuid4().hex,
             'created_at': datetime.now(timezone.utc).isoformat(), 'mode': mode,
             'source_type': source, 'repo': diff['repo'],
             'base_sha': diff.get('comparison_base_sha', diff.get('base_sha')),
             'head_sha': diff['head_sha'], 'head_repo': diff.get('head_repo') or diff['repo'],
             'diff': diff, 'evidence': [], 'failed_reads': [], 'saves': []}
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix='codediff-', dir=root))
    try:
        write_manifest(directory, state)
    except Exception:
        shutil.rmtree(directory)
        raise
    return {'status': 'ready', 'analysis_id': state['analysis_id'],
            'session_dir': str(directory), 'diff': diff}


def validate_evidence(state):
    full_sha(state['base_sha'])
    full_sha(state['head_sha'])
    diff = state['diff']
    if (state['repo'] != diff['repo'] or state['head_sha'] != diff['head_sha']
            or state['base_sha'] != diff.get('comparison_base_sha', diff.get('base_sha'))
            or state['source_type'] != diff['source_type']
            or state['head_repo'] != (diff.get('head_repo') or diff['repo'])):
        raise SessionError('INVALID_SESSION', '会话版本或仓库与原始 diff 不一致。')
    seen = set()
    for item in state['evidence']:
        if (item['id'] in seen or not re.fullmatch(r'E[0-9]{4}', item['id'])
                or item['side'] not in ('base', 'head')
                or item['commit_sha'] != state[item['side'] + '_sha']
                or item['repo'] != (state['head_repo'] if item['side'] == 'head' else state['repo'])
                or item['sha256'] != digest(item['content'])
                or item['line_count'] != len(item['content'].splitlines())):
            raise SessionError('INVALID_EVIDENCE', '证据的版本、仓库、内容摘要或行数不匹配。')
        seen.add(item['id'])


def read_evidence(session, path, side='head'):
    if side not in ('base', 'head'):
        raise SessionError('INVALID_INPUT', 'side 仅允许 base/head。')
    with locked_session(session) as (directory, state):
        validate_evidence(state)
        repo = state['head_repo'] if side == 'head' else state['repo']
        sha = state[side + '_sha']
        try:
            if len(state['evidence']) >= MAX_FILES:
                raise SessionError('SESSION_LIMIT', '已读取50份文件证据，请停止取证并注明范围缺口。')
            if state['source_type'] == 'local_git':
                result = read_local_file(repo, sha, path)
            else:
                result = GitHubReader(repo).read_file(sha, path)
            size = sum(len(e['content'].encode('utf-8')) for e in state['evidence'])
            if size + len(result['content'].encode('utf-8')) > MAX_CONTENT_BYTES:
                raise SessionError('SESSION_LIMIT', '文件证据合计超过8MB，请停止取证并注明范围缺口。')
            item = {**result, 'id': f'E{len(state["evidence"]) + 1:04d}',
                    'side': side, 'sha256': digest(result['content'])}
            state['evidence'].append(item)
        except (DiffError, GitHubError, SessionError) as error:
            # Keep error codes, not API bodies, environment or credentials.
            state['failed_reads'].append({'side': side, 'path': path, 'repo': repo,
                                          'commit_sha': sha, 'code': error.code})
            state['failed_reads'] = state['failed_reads'][-100:]
            write_manifest(directory, state)
            raise
        write_manifest(directory, state)
        return {'analysis_id': state['analysis_id'], 'evidence': item}


def coverage(state):
    unread = []
    read = {(e['side'], e['path']) for e in state['evidence']}
    for file in state['diff']['files']:
        side = 'base' if file['status'] == 'removed' else 'head'
        if (side, file['path']) not in read:
            unread.append({'side': side, 'path': file['path']})
    return {'unread_files': unread, 'failed_reads': state['failed_reads'],
            'diff_complete': state['diff'].get('complete'),
            'coverage_note': '文件已读取不代表语义覆盖；API patch 可能截断；跨服务依赖与需求覆盖由分析明确说明。'}


def session_status(session):
    with locked_session(session) as (_, state):
        validate_evidence(state)
        return {**{k: state[k] for k in ('analysis_id', 'repo', 'base_sha', 'head_sha', 'saves')},
                'evidence': [{k: v for k, v in e.items() if k != 'content'} for e in state['evidence']],
                **coverage(state)}


def validate_citation(reference, evidence):
    if not isinstance(reference, str) or not CITATION.fullmatch(reference):
        raise SessionError('INVALID_EVIDENCE', '证据引用格式必须为 E0001:L1 或 E0001:L1-L2。')
    identifier, lines = reference.split(':L')
    start, _, end = lines.partition('-L')
    start, end = int(start), int(end or start)
    if identifier not in evidence or not 1 <= start <= end <= evidence[identifier]['line_count']:
        raise SessionError('INVALID_EVIDENCE', '证据不存在或引用行号超出已读取文件。')


def save_session(session, payload, output_dir):
    if not isinstance(payload, dict) or set(payload) - {'report_markdown', 'test_cases'}:
        raise SessionError('INVALID_INPUT', '分析 JSON 仅允许 report_markdown 和 test_cases；版本取自会话。')
    with locked_session(session) as (directory, state):
        validate_evidence(state)
        report = payload.get('report_markdown')
        cases = payload.get('test_cases', [])
        _validate(state['mode'], state['repo'], state['base_sha'], state['head_sha'], report, cases)
        evidence = {e['id']: e for e in state['evidence']}
        for case in cases:
            for reference in case['evidence']:
                validate_citation(reference, evidence)
        references = REPORT_REFERENCE.findall(report)
        if any(e['line_count'] for e in evidence.values()) and not references:
            raise SessionError('INVALID_EVIDENCE', '已读取代码时，报告需引用至少一处实际文件证据。')
        for reference in references:
            validate_citation(reference, evidence)
        summary = coverage(state)
        appendix = '\n\n## 脚本记录的证据范围\n\n分析标识：' + state['analysis_id'] + '\n\n'
        for item in state['evidence']:
            appendix += (f'- {item["id"]}: {item["repo"]} @ {item["commit_sha"]} / '
                         f'{item["path"]}；{item["line_count"]}行；SHA256={item["sha256"]}\n')
        appendix += '\n未读取的变更文件：\n'
        appendix += ''.join(f'- {f["side"]}: {f["path"]}\n' for f in summary['unread_files']) or '- 无\n'
        appendix += '\n读取失败记录：\n'
        appendix += ''.join(f'- {f["path"]}: {f["code"]}\n' for f in summary['failed_reads']) or '- 无\n'
        appendix += '\n' + summary['coverage_note'] + '\n'
        appendix += '\ndiff_complete=' + json.dumps(summary['diff_complete'])
        appendix += '；file_list_complete=' + json.dumps(state['diff'].get('file_list_complete')) + '\n'
        appendix += '\nDiff 限制：' + '；'.join(state['diff'].get('limitations', [])) + '\n'
        bundle = {**state, **summary}
        saved = save_analysis(state['mode'], state['repo'], state['base_sha'], state['head_sha'],
                              report + appendix, output_dir, cases)
        evidence_path = Path(saved['directory']) / 'evidence.json'
        try:
            _write_text(evidence_path, json.dumps(bundle, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
            state['saves'].append(saved)
            write_manifest(directory, state)
        except Exception:
            shutil.rmtree(saved['directory'])
            raise
        return {**saved, 'analysis_id': state['analysis_id'], 'evidence_path': str(evidence_path)}
