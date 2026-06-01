#!/usr/bin/env python3
"""Analyze Java/Spring impact from structured GitHub diff JSON.

This is intentionally dependency-free. It uses pragmatic regex parsing first;
future versions can replace internals with tree-sitter-java without changing the
JSON contract.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HTTP_BY_ANNOTATION = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

MAPPING_ANNOTATIONS = tuple(HTTP_BY_ANNOTATION) + ("RequestMapping",)
VALIDATION_ANNOTATIONS = {
    "NotNull",
    "NotBlank",
    "NotEmpty",
    "Size",
    "Length",
    "Min",
    "Max",
    "Pattern",
    "Email",
    "Positive",
    "PositiveOrZero",
    "Negative",
    "NegativeOrZero",
    "DecimalMin",
    "DecimalMax",
}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_path(path: str) -> str:
    lower = path.lower()
    name = Path(path).name
    if lower.endswith("pom.xml") or lower.endswith("build.gradle") or lower.endswith("build.gradle.kts"):
        return "dependency"
    if any(part in lower for part in ("application.yml", "application.yaml", "application.properties", "bootstrap.yml", "bootstrap.yaml")):
        return "config"
    if "/src/test/" in lower or name.endswith("Test.java") or name.endswith("IT.java"):
        return "test"
    if lower.endswith(".xml") and ("mapper" in lower or "mybatis" in lower):
        return "mapper_xml"
    if not lower.endswith(".java"):
        return "other"
    if name.endswith("Controller.java") or "controller" in lower:
        return "controller"
    if name.endswith("Service.java") or name.endswith("ServiceImpl.java") or "service" in lower:
        return "service"
    if name.endswith("Mapper.java") or name.endswith("Dao.java") or "mapper" in lower or "dao" in lower:
        return "mapper_java"
    if name.endswith("Repository.java") or "repository" in lower:
        return "repository"
    if name.endswith("Entity.java") or "/entity/" in lower or "/domain/" in lower:
        return "entity"
    if re.search(r"(dto|vo|bo|form|request|response|req|resp)\.java$", lower):
        return "dto"
    return "java"


def read_context(repo_root: Optional[Path], file_info: Dict[str, Any]) -> str:
    path = file_info.get("path") or ""
    if repo_root:
        candidate = repo_root / path
        if candidate.exists() and candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return file_info.get("patch") or ""


def extract_quoted(annotation: str) -> str:
    path_match = re.search(r"(?:value\s*=\s*|path\s*=\s*)?\{?\s*\"([^\"]+)\"", annotation)
    return path_match.group(1) if path_match else ""


def normalize_path(*parts: str) -> str:
    segments: List[str] = []
    for part in parts:
        if not part:
            continue
        stripped = part.strip().strip('"')
        if not stripped:
            continue
        segments.append(stripped.strip("/"))
    if not segments:
        return "/"
    return "/" + "/".join(seg for seg in segments if seg)


def extract_request_method(annotation_name: str, annotation_text: str) -> str:
    if annotation_name in HTTP_BY_ANNOTATION:
        return HTTP_BY_ANNOTATION[annotation_name]
    method_match = re.search(r"RequestMethod\.([A-Z]+)", annotation_text)
    return method_match.group(1) if method_match else "ANY"


def method_signature(line: str) -> Optional[Dict[str, str]]:
    cleaned = line.strip()
    match = re.search(
        r"(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?([\w<>?,\s\.]+?)\s+(\w+)\s*\(([^)]*)\)",
        cleaned,
    )
    if not match:
        return None
    params = match.group(3)
    request_dto = ""
    body_match = re.search(r"@RequestBody\s+(?:@\w+\s+)*([\w<>.]+)", params)
    if body_match:
        request_dto = body_match.group(1)
    return {
        "return_type": " ".join(match.group(1).split()),
        "method_name": match.group(2),
        "params": " ".join(params.split()),
        "request_dto": request_dto,
    }


def extract_controller_apis(content: str, path: str) -> List[Dict[str, Any]]:
    if "@RestController" not in content and "@Controller" not in content and "Mapping" not in content:
        return []

    class_base = ""
    class_match = re.search(r"((?:@\w+(?:\([^)]*\))?\s*)*)\s*public\s+class\s+(\w+)", content, re.S)
    class_name = Path(path).stem
    if class_match:
        annotations, class_name = class_match.group(1), class_match.group(2)
        base_match = re.search(r"@RequestMapping\s*\(([^)]*)\)", annotations, re.S)
        if base_match:
            class_base = extract_quoted(base_match.group(1))

    apis: List[Dict[str, Any]] = []
    pending_annotations: List[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("@"):
            pending_annotations.append(line)
            continue
        sig = method_signature(line)
        if not sig:
            if line and not line.startswith("@") and not line.startswith("//"):
                pending_annotations = []
            continue
        annotation_blob = " ".join(pending_annotations)
        pending_annotations = []
        for name in MAPPING_ANNOTATIONS:
            ann_match = re.search(rf"@{name}\s*(?:\((.*?)\))?", annotation_blob)
            if not ann_match:
                continue
            ann_text = ann_match.group(1) or ""
            apis.append(
                {
                    "method": extract_request_method(name, ann_text),
                    "path": normalize_path(class_base, extract_quoted(ann_text)),
                    "controller": class_name,
                    "handler": sig["method_name"],
                    "request_dto": sig["request_dto"],
                    "response_dto": sig["return_type"],
                    "evidence": path,
                    "confidence": "medium" if "${" in ann_text or "+" in ann_text else "high",
                }
            )
            break
    return apis


def extract_dto_fields(content: str, path: str) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    annotations: List[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("@"):
            annotations.append(line)
            continue
        match = re.search(r"(?:private|protected|public)\s+([\w<>.?]+)\s+(\w+)\s*(?:=|;)", line)
        if not match:
            if line and not line.startswith("//"):
                annotations = []
            continue
        validators = []
        for ann in annotations:
            name_match = re.match(r"@(\w+)", ann)
            if name_match and name_match.group(1) in VALIDATION_ANNOTATIONS:
                validators.append(ann)
        fields.append(
            {
                "file": path,
                "type": match.group(1),
                "name": match.group(2),
                "validators": validators,
            }
        )
        annotations = []
    return fields


def extract_changed_methods_from_patch(patch: str) -> List[str]:
    methods: List[str] = []
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        sig = method_signature(line[1:])
        if sig and sig["method_name"] not in methods:
            methods.append(sig["method_name"])
    return methods


def summarize_risk(area: str, path: str, methods: Iterable[str]) -> Dict[str, Any]:
    methods_text = ", ".join(methods) if methods else "changed code"
    suggestions = {
        "controller": "Cover direct API success, validation failure, auth/permission, and compatibility cases.",
        "service": "Cover main business branch, new conditions, exception paths, and upstream API flows.",
        "dto": "Cover required fields, invalid formats, boundary values, and backward compatibility.",
        "mapper_xml": "Cover SQL result shape, empty result, multi-row data, pagination/sorting, and write consistency.",
        "mapper_java": "Cover DAO query/update behavior and data consistency.",
        "repository": "Cover repository query/write behavior and transaction boundaries.",
        "entity": "Cover schema compatibility, serialization, and historical data behavior.",
        "config": "Cover application startup, environment overrides, feature flags, and rollback behavior.",
        "dependency": "Cover build, dependency conflict, runtime startup, and compatibility checks.",
        "test": "Check whether updated tests cover the changed production behavior.",
    }
    return {
        "type": area,
        "file": path,
        "method_or_scope": methods_text,
        "suggestion": suggestions.get(area, "Review changed behavior and add focused regression checks."),
    }


def analyze(diff: Dict[str, Any], repo_root: Optional[Path]) -> Dict[str, Any]:
    analyzed_files: List[Dict[str, Any]] = []
    apis: List[Dict[str, Any]] = []
    dto_changes: List[Dict[str, Any]] = []
    risks: List[Dict[str, Any]] = []
    uncertainties: List[str] = []

    for file_info in diff.get("files", []):
        path = file_info.get("path") or ""
        area = classify_path(path)
        patch = file_info.get("patch") or ""
        content = read_context(repo_root, file_info)
        changed_methods = extract_changed_methods_from_patch(patch)
        file_record = {
            "path": path,
            "status": file_info.get("status"),
            "area": area,
            "additions": file_info.get("additions", 0),
            "deletions": file_info.get("deletions", 0),
            "changed_methods": changed_methods,
        }
        analyzed_files.append(file_record)

        if area == "controller" or "Mapping" in content:
            found = extract_controller_apis(content, path)
            apis.extend(found)
            if area == "controller" and not found:
                uncertainties.append(f"Controller-like file has no statically extracted endpoint: {path}")
        if area == "dto" or any(token in Path(path).name for token in ("DTO", "Req", "Request", "Resp", "Response")):
            dto_changes.extend(extract_dto_fields(content, path))
        if area in {"controller", "service", "dto", "mapper_xml", "mapper_java", "repository", "entity", "config", "dependency", "test"}:
            risks.append(summarize_risk(area, path, changed_methods))
        if file_info.get("status") == "removed":
            uncertainties.append(f"Removed file may affect callers not visible in diff: {path}")
        if not patch and area != "other":
            uncertainties.append(f"Patch unavailable or too large for file; analysis may require local context: {path}")

    area_counts: Dict[str, int] = {}
    for item in analyzed_files:
        area_counts[item["area"]] = area_counts.get(item["area"], 0) + 1

    return {
        "source": {
            "source_type": diff.get("source_type"),
            "repo": diff.get("repo"),
            "pr_number": diff.get("pr_number"),
            "title": diff.get("title"),
            "html_url": diff.get("html_url"),
            "base_ref": diff.get("base_ref"),
            "head_ref": diff.get("head_ref"),
            "base_sha": diff.get("base_sha"),
            "head_sha": diff.get("head_sha"),
        },
        "summary": {
            "changed_file_count": len(analyzed_files),
            "area_counts": area_counts,
            "api_count": len(apis),
            "dto_field_count": len(dto_changes),
            "risk_count": len(risks),
        },
        "files": analyzed_files,
        "apis": apis,
        "dto_changes": dto_changes,
        "risks": risks,
        "uncertainties": uncertainties,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Java/Spring diff impact")
    parser.add_argument("--diff-json", required=True, help="Input diff JSON from github_pr_diff.py")
    parser.add_argument("--repo-root", help="Optional local repository root for full file context")
    parser.add_argument("--output", "-o", default="impact.json", help="Output impact JSON")
    args = parser.parse_args()

    diff = load_json(Path(args.diff_json))
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    impact = analyze(diff, repo_root)
    Path(args.output).write_text(json.dumps(impact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {args.output}: {impact['summary']['changed_file_count']} files, "
        f"{impact['summary']['api_count']} APIs, {impact['summary']['risk_count']} risks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
