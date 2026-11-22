"""Best-effort diff coordinates and Python symbol ownership; no source execution."""
import ast
from pathlib import PurePosixPath
import re

_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$')


def changed_lines(patch, *, additions=None, deletions=None, binary=False):
    """Parse a single file's unified patch, preserving observed lines on truncation."""
    result = {'added': [], 'deleted': [], 'status': 'unavailable', 'limitations': []}
    if binary:
        result['status'] = 'binary'
        result['limitations'].append('二进制文件没有可映射的文本变更行。')
        return result
    if not isinstance(patch, str):
        result['limitations'].append('未提供文本 patch，无法提取变更行。')
        return result
    old = new = old_left = new_left = 0
    hunks = 0
    invalid = False
    for line in patch.split('\n'):
        match = _HUNK.fullmatch(line)
        if match:
            invalid |= bool(old_left or new_left)
            old, old_count, new, new_count = match.groups()
            old, new = int(old), int(new)
            old_left, new_left = int(old_count or 1), int(new_count or 1)
            invalid |= (old_left > 0 and old < 1) or (new_left > 0 and new < 1)
            hunks += 1
            continue
        if line.startswith('\\ No newline at end of file'):
            continue
        if not (old_left or new_left):
            # Headers and mode/rename metadata are outside hunks.
            if line.startswith('@@') or (hunks and line and line[0] in ' +-'):
                invalid = True
            continue
        prefix = line[:1]
        take_old = prefix in (' ', '-')
        take_new = prefix in (' ', '+')
        if not (take_old or take_new) or (take_old and old_left <= 0) or (take_new and new_left <= 0):
            invalid = True
            continue
        if prefix == '-':
            result['deleted'].append(old)
        elif prefix == '+':
            result['added'].append(new)
        if take_old:
            old += 1
            old_left -= 1
        if take_new:
            new += 1
            new_left -= 1
    invalid |= bool(old_left or new_left)
    invalid |= additions is not None and len(result['added']) != additions
    invalid |= deletions is not None and len(result['deleted']) != deletions
    if invalid:
        result['status'] = 'partial'
        result['limitations'].append('patch 不完整、格式异常或变更行数与统计不符；仅保留已观察行，不代表完整覆盖。')
    elif hunks:
        result['status'] = 'complete'
    elif additions == 0 and deletions == 0:
        result['status'] = 'no_text_changes'
    else:
        result['limitations'].append('没有可解析的文本 hunk，不能推断没有变更。')
    return result


class _PythonSymbols(ast.NodeVisitor):
    def __init__(self):
        self.symbols = []
        self.stack = []

    def _definition(self, node):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        parents = [self.symbols[i]['qualified_name'] for i in self.stack]
        record = {'name': node.name, 'qualified_name': '.'.join([*parents[-1:], node.name]),
                  'kind': 'class' if isinstance(node, ast.ClassDef) else 'function',
                  'start_line': start, 'end_line': node.end_lineno,
                  'ancestors': parents, 'changed_lines': []}
        if isinstance(node, ast.AsyncFunctionDef):
            record['kind'] = 'async_function'
        if self.stack and self.symbols[self.stack[-1]]['kind'] == 'class' and record['kind'] != 'class':
            record['kind'] = 'async_method' if isinstance(node, ast.AsyncFunctionDef) else 'method'
        index = len(self.symbols)
        self.symbols.append(record)
        self.stack.append(index)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = _definition
    visit_FunctionDef = _definition
    visit_AsyncFunctionDef = _definition


def locate_symbols(path, content, lines, line_status):
    """Return ownership for one read version; no cross-version symbol pairing."""
    result = {'language': 'python' if PurePosixPath(path).suffix == '.py' else None,
              'status': 'complete', 'line_status': line_status, 'symbols': [],
              'module_lines': [], 'unmapped_lines': [], 'limitations': []}
    if result['language'] is None:
        result.update(status='unsupported_language', unmapped_lines=list(lines))
        result['limitations'].append('当前仅支持 Python 符号定位。')
        return result
    try:
        tree = ast.parse(content, filename=path)
        visitor = _PythonSymbols()
        visitor.visit(tree)
    except (SyntaxError, ValueError, RecursionError):
        result.update(status='parse_error', unmapped_lines=list(lines))
        result['limitations'].append('源码不能由当前 Python 解释器解析，未猜测符号范围。')
        return result
    count = len(content.splitlines())
    for line in sorted(set(lines)):
        if not 1 <= line <= count:
            result['unmapped_lines'].append(line)
            continue
        matches = [s for s in visitor.symbols if s['end_line'] is not None and s['start_line'] <= line <= s['end_line']]
        if matches:
            owner = max(matches, key=lambda s: len(s['ancestors']))
            owner['changed_lines'].append(line)
        else:
            result['module_lines'].append(line)
    result['symbols'] = visitor.symbols
    if result['unmapped_lines'] or line_status not in ('complete', 'no_text_changes'):
        result['status'] = 'partial'
        result['limitations'].append('变更行不完整或存在无法定位的行；符号列表不代表完整影响范围。')
    result['limitations'].append('仅定位语法归属，不判断行为变化、调用关系或跨版本符号身份；注释/空白可能不在 AST 范围内。')
    return result
