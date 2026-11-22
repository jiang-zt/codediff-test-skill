#!/usr/bin/env python3
"""Standalone CodeDiff Skill interface. stdout is JSON; no MCP or model SDK needed."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.analysis_artifacts import ArtifactError
from tools.github_reader import GitHubError
from tools.local_git_diff import DiffError
from tools.evidence_session import (SessionError, read_json, read_evidence, save_session,
                                    session_status, start_session)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may include supplied values, so don't echo raw arguments or secrets.
        raise SessionError('INVALID_ARGUMENTS', '命令或参数无效；使用 --help 查看接口。')

    def print_help(self, file=None):
        print(json.dumps({'ok': True, 'help': self.format_help()}, ensure_ascii=False))


def main(argv=None):
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    local = commands.add_parser('start-local', help='Pin a local comparison and create an evidence session')
    local.add_argument('--repo-path', required=True)
    local.add_argument('--base', required=True)
    local.add_argument('--head', required=True)
    local.add_argument('--session-root', required=True)
    github = commands.add_parser('start-github', help='Pin GitHub PR review or ancestor-base test comparison')
    github.add_argument('--repo', required=True)
    github.add_argument('--mode', required=True, choices=['review', 'test'])
    github.add_argument('--pr-number', type=int)
    github.add_argument('--sha')
    github.add_argument('--base-sha')
    github.add_argument('--head-sha')
    github.add_argument('--session-root', required=True)
    read = commands.add_parser('read', help='Read a full file at a session-pinned SHA')
    read.add_argument('--session', required=True)
    read.add_argument('--path', required=True)
    read.add_argument('--side', choices=['base', 'head'], default='head')
    status = commands.add_parser('status', help='Inspect evidence, unread paths and failures')
    status.add_argument('--session', required=True)
    save = commands.add_parser('save', help='Validate analysis JSON and publish report plus evidence bundle')
    save.add_argument('--session', required=True)
    save.add_argument('--input', required=True)
    save.add_argument('--output-dir', required=True)
    try:
        args = vars(parser.parse_args(argv))
        command = args.pop('command')
        if command == 'start-local':
            result = start_session('local_git', **args)
        elif command == 'start-github':
            if args['mode'] == 'test':
                if not args['base_sha'] or not args['head_sha'] or args['pr_number'] is not None or args['sha']:
                    parser.error('invalid test input')
            elif args['base_sha'] or args['head_sha'] or (args['pr_number'] is None and not args['sha']):
                parser.error('invalid review input')
            result = start_session('github', **args)
        elif command == 'read':
            result = read_evidence(**args)
        elif command == 'status':
            result = session_status(**args)
        else:
            result = save_session(args['session'], read_json(args['input'], limit=2_000_000), args['output_dir'])
        print(json.dumps({'ok': True, **result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (SessionError, DiffError, GitHubError, ArtifactError) as error:
        print(json.dumps({'ok': False, 'error': {'code': error.code, 'message': str(error)}}, ensure_ascii=False))
        return 2 if error.code == 'INVALID_ARGUMENTS' else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print(json.dumps({'ok': False, 'error': {'code': 'INVALID_INPUT_OR_IO',
                          'message': '无法处理输入或访问文件；检查会话格式、路径、权限及磁盘空间。'}}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
