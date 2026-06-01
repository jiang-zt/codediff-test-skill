#!/usr/bin/env python3
"""Build a Markdown test impact report from impact JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return "_无。_\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        escaped = [str(cell).replace("\n", "<br>").replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines) + "\n"


def priority_for_risk(risk_type: str) -> str:
    if risk_type in {"controller", "service", "dto", "mapper_xml", "mapper_java", "repository", "config", "dependency"}:
        return "P0"
    if risk_type in {"entity", "test"}:
        return "P1"
    return "P2"


def build_cases(impact: Dict[str, Any]) -> List[Dict[str, str]]:
    cases: List[Dict[str, str]] = []
    for api in impact.get("apis", []):
        label = f"{api.get('method', 'ANY')} {api.get('path', '/')}"
        evidence = api.get("evidence", "")
        cases.append({
            "target": label,
            "scenario": "正常请求成功路径",
            "precondition": "准备合法请求参数、鉴权与测试数据",
            "assertion": "返回 2xx，响应结构与业务状态符合预期",
            "priority": "P0",
            "evidence": evidence,
        })
        cases.append({
            "target": label,
            "scenario": "参数缺失或非法值",
            "precondition": "按请求 DTO 构造缺失必填、格式错误、边界值参数",
            "assertion": "返回明确错误码/错误信息，服务端无脏数据写入",
            "priority": "P0",
            "evidence": evidence,
        })
        cases.append({
            "target": label,
            "scenario": "鉴权、权限或租户隔离检查",
            "precondition": "使用无 token、低权限账号、跨租户数据分别请求",
            "assertion": "未授权/无权限请求被拒绝，合法用户访问正常",
            "priority": "P1",
            "evidence": evidence,
        })
    for risk in impact.get("risks", []):
        if risk.get("type") == "service":
            cases.append({
                "target": risk.get("method_or_scope", "Service changed code"),
                "scenario": "业务规则主分支和新增条件分支",
                "precondition": "准备覆盖正常、边界、异常输入的业务数据",
                "assertion": "业务结果、状态流转、异常处理与预期一致",
                "priority": "P0",
                "evidence": risk.get("file", ""),
            })
        elif risk.get("type") in {"mapper_xml", "mapper_java", "repository"}:
            cases.append({
                "target": risk.get("file", "DB access"),
                "scenario": "数据访问与历史数据兼容",
                "precondition": "准备空结果、单条、多条、历史数据、边界分页数据",
                "assertion": "查询/写入结果正确，无重复、漏查、排序或事务异常",
                "priority": "P0",
                "evidence": risk.get("file", ""),
            })
    return cases


def build_report(impact: Dict[str, Any]) -> str:
    source = impact.get("source", {})
    summary = impact.get("summary", {})
    lines: List[str] = []
    lines.append("# PR 测试影响分析报告\n")

    lines.append("## 1. PR 信息\n")
    lines.append(table(
        ["字段", "值"],
        [
            ["仓库", source.get("repo") or "待确认"],
            ["PR / Compare", str(source.get("pr_number") or source.get("source_type") or "待确认")],
            ["标题", source.get("title") or "待确认"],
            ["Base", source.get("base_ref") or source.get("base_sha") or "待确认"],
            ["Head", source.get("head_ref") or source.get("head_sha") or "待确认"],
            ["链接", source.get("html_url") or "待确认"],
        ],
    ))

    lines.append("## 2. 变更摘要\n")
    area_counts = summary.get("area_counts", {})
    lines.append(f"- 变更文件数：{summary.get('changed_file_count', 0)}")
    lines.append(f"- 识别到接口数：{summary.get('api_count', 0)}")
    lines.append(f"- 识别到 DTO 字段数：{summary.get('dto_field_count', 0)}")
    lines.append(f"- 风险项数：{summary.get('risk_count', 0)}")
    if area_counts:
        lines.append("- 文件类型分布：" + ", ".join(f"{k}={v}" for k, v in sorted(area_counts.items())))
    lines.append("")

    lines.append("## 3. 变更文件分类\n")
    lines.append(table(
        ["文件", "类型", "状态", "增/删", "变更方法"],
        [
            [
                item.get("path", ""),
                item.get("area", ""),
                item.get("status", ""),
                f"+{item.get('additions', 0)} / -{item.get('deletions', 0)}",
                ", ".join(item.get("changed_methods") or []) or "未从 patch 提取",
            ]
            for item in impact.get("files", [])
        ],
    ))

    lines.append("## 4. 受影响接口\n")
    lines.append(table(
        ["方法", "路径", "Controller", "Handler", "请求 DTO", "响应 DTO", "置信度", "证据"],
        [
            [
                api.get("method", ""),
                api.get("path", ""),
                api.get("controller", ""),
                api.get("handler", ""),
                api.get("request_dto", "") or "待确认",
                api.get("response_dto", "") or "待确认",
                api.get("confidence", ""),
                api.get("evidence", ""),
            ]
            for api in impact.get("apis", [])
        ],
    ))

    lines.append("## 5. 建议接口测试用例\n")
    cases = build_cases(impact)
    lines.append(table(
        ["优先级", "对象", "场景", "前置条件 / 数据", "断言", "证据"],
        [[c["priority"], c["target"], c["scenario"], c["precondition"], c["assertion"], c["evidence"]] for c in cases],
    ))

    lines.append("## 6. 回归范围\n")
    regression_rows = []
    for risk in impact.get("risks", []):
        regression_rows.append([
            priority_for_risk(risk.get("type", "")),
            risk.get("file", ""),
            risk.get("type", ""),
            risk.get("suggestion", ""),
            risk.get("method_or_scope", ""),
        ])
    regression_rows.sort(key=lambda row: row[0])
    lines.append(table(["优先级", "范围", "风险类型", "建议检查", "方法/位置"], regression_rows))

    lines.append("## 7. 数据库 / 配置 / 依赖风险\n")
    focused = [r for r in impact.get("risks", []) if r.get("type") in {"mapper_xml", "mapper_java", "repository", "entity", "config", "dependency"}]
    lines.append(table(
        ["类型", "文件", "建议"],
        [[r.get("type", ""), r.get("file", ""), r.get("suggestion", "")] for r in focused],
    ))

    lines.append("## 8. 建议补充的自动化测试\n")
    automation = []
    if impact.get("apis"):
        automation.append(["接口自动化", "为 P0 接口生成 Postman 或接口自动化脚本，覆盖成功、参数校验、鉴权失败。"])
    if any(r.get("type") == "service" for r in impact.get("risks", [])):
        automation.append(["单元/集成测试", "为变更 Service 方法补充核心业务分支、异常分支和边界值测试。"])
    if any(r.get("type") in {"mapper_xml", "mapper_java", "repository"} for r in impact.get("risks", [])):
        automation.append(["数据层测试", "增加带测试数据准备和清理的数据访问回归用例。"])
    lines.append(table(["类型", "建议"], automation))

    lines.append("## 9. 不确定项与人工确认项\n")
    uncertainties = [[item] for item in impact.get("uncertainties", [])]
    if not uncertainties:
        uncertainties = [["未发现必须人工确认的不确定项；仍需测试人员补充鉴权、环境和真实测试数据。"]]
    lines.append(table(["确认项"], uncertainties))

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Markdown test impact report")
    parser.add_argument("--impact-json", required=True)
    parser.add_argument("--output", "-o", default="test-impact-report.md")
    args = parser.parse_args()
    impact = load(Path(args.impact_json))
    Path(args.output).write_text(build_report(impact), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
