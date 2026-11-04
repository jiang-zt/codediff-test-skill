"""Save model-authored reports and draft test cases to the directory explicitly supplied by the user."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

MAX_BYTES = 2_000_000


class ArtifactError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ArtifactError('INVALID_INPUT', f'{name} 必须为非空文本。')


def _validate(mode, repo, base_sha, head_sha, report_markdown, test_cases):
    if mode not in ('review', 'test'):
        raise ArtifactError('INVALID_INPUT', 'mode 必须为 review 或 test。')
    _text(repo, 'repo')
    if len(repo)>1000 or any(ord(c)<32 for c in repo):
        raise ArtifactError('INVALID_INPUT', 'repo 格式无效。')
    for name, sha in (('base_sha', base_sha), ('head_sha', head_sha)):
        if not isinstance(sha,str) or not re.fullmatch(r'[0-9a-fA-F]{40}',sha):
            raise ArtifactError('INVALID_INPUT', f'{name} 必须为工具实际返回的40位SHA。')
    _text(report_markdown, 'report_markdown')
    if not isinstance(test_cases,list) or len(test_cases)>500:
        raise ArtifactError('INVALID_CASES', 'test_cases 必须为列表，最多500条；没有依据时传空列表。')
    for index, case in enumerate(test_cases, 1):
        if not isinstance(case,dict):
            raise ArtifactError('INVALID_CASES', f'用例{index}必须为对象。')
        _text(case.get('name'), f'用例{index}.name')
        if case.get('priority','P1') not in ('P0','P1','P2'):
            raise ArtifactError('INVALID_CASES', f'用例{index}.priority 仅允许P0/P1/P2。')
        steps = case.get('steps')
        if not isinstance(steps,list) or not steps or len(steps)>100:
            raise ArtifactError('INVALID_CASES', f'用例{index}.steps 需有1至100个步骤。')
        for step in steps:
            if not isinstance(step,dict):
                raise ArtifactError('INVALID_CASES', f'用例{index}步骤必须为对象。')
            _text(step.get('action'), 'action')
            _text(step.get('expected'), 'expected')
        evidence = case.get('evidence')
        if not isinstance(evidence,list) or not evidence:
            raise ArtifactError('INVALID_CASES', f'用例{index}必须提供evidence证据列表。')
        for item in evidence:
            _text(item, 'evidence')
    try:
        repo.encode('utf-8')
        size = len(report_markdown.encode('utf-8')) + len(json.dumps(test_cases,ensure_ascii=False,allow_nan=False).encode('utf-8'))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ArtifactError('INVALID_INPUT', '内容必须为可序列化的UTF-8文本和JSON。') from None
    if size>MAX_BYTES:
        raise ArtifactError('OUTPUT_TOO_LARGE', '报告与用例合计超过2MB，请缩小分析范围。')


def _write_text(path: Path, text: str):
    # Private files, exclusive creation. Generated text never becomes shell code or a filename.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(text)


def save_analysis(mode: str, repo: str, base_sha: str, head_sha: str,
                  report_markdown: str, output_dir: str, test_cases: list[dict] | None = None) -> dict:
    cases = [] if test_cases is None else test_cases
    _validate(mode, repo, base_sha, head_sha, report_markdown, cases)
    if not isinstance(output_dir,str) or not output_dir.strip() or any(ord(c)<32 for c in output_dir):
        raise ArtifactError('INVALID_OUTPUT_DIR', '请在对话中提供保存目录的绝对路径。')
    try:
        output_dir.encode('utf-8')
        root = Path(output_dir).expanduser()
        if not root.is_absolute():
            raise ArtifactError('INVALID_OUTPUT_DIR', '请提供保存目录的绝对路径，不接受相对路径。')
        root = root.resolve()
    except (OSError, UnicodeError, RuntimeError):
        raise ArtifactError('INVALID_OUTPUT_DIR', '保存目录路径无效或不可解析。') from None
    now = datetime.now(timezone.utc)
    metadata = {'schema_version':1, 'generated_at':now.isoformat(), 'mode':mode,
                'repo':repo, 'base_sha':base_sha.lower(), 'head_sha':head_sha.lower(),
                'status':'draft', 'case_count':len(cases)}
    title = 'PR评审报告' if mode=='review' else '提测分析报告'
    report = (f'# {title}\n\n仓库：{repo}\n\n'
              f'比较基线：`{metadata["base_sha"]}`\n\n目标版本：`{metadata["head_sha"]}`\n\n'
              f'生成时间（UTC）：{metadata["generated_at"]}\n\n'
              f'{report_markdown.rstrip()}\n\n## 测试用例草稿\n\n')
    if not cases:
        report += '本次未保存测试用例；请参见分析中的证据限制或待确认项。\n'
    for index, case in enumerate(cases, 1):
        report += f'### {index}. {case["name"]}\n\n优先级：{case.get("priority","未指定")}\n\n'
        for number, step in enumerate(case['steps'], 1):
            report += f'{number}. 操作：{step["action"]}\n\n   预期：{step["expected"]}\n\n'
        report += '证据：' + '；'.join(case['evidence']) + '\n\n'
    report += '\n用例为模型生成的草稿，未执行测试。\n'
    payload = json.dumps({**metadata, 'cases':cases}, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    directory = None
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = Path(tempfile.mkdtemp(prefix=f'{mode}-{now:%Y%m%dT%H%M%SZ}-',dir=root))
        _write_text(directory/'report.md', report)
        _write_text(directory/'test_cases.json', payload)
    except OSError:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        raise ArtifactError('SAVE_FAILED', '报告保存失败，请检查输出目录权限或磁盘空间；未返回成功回执。') from None
    return {'status':'saved', 'directory':str(directory),
            'report_path':str(directory/'report.md'), 'test_cases_path':str(directory/'test_cases.json'),
            'case_count':len(cases), 'generated_at':metadata['generated_at']}
