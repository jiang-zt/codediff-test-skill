#!/usr/bin/env python3
"""Build a basic Postman collection from detected Spring APIs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def path_segments(path: str) -> List[str]:
    return [seg for seg in path.strip("/").split("/") if seg]


def sample_body(api: Dict[str, Any]) -> str:
    dto = api.get("request_dto") or "RequestBody"
    return json.dumps({"_todo": f"Fill sample payload for {dto}"}, ensure_ascii=False, indent=2)


def build_item(api: Dict[str, Any], base_url_var: str) -> Dict[str, Any]:
    method = api.get("method") or "GET"
    path = api.get("path") or "/"
    item: Dict[str, Any] = {
        "name": f"{method} {path} - {api.get('handler') or 'handler'}",
        "request": {
            "method": method if method != "ANY" else "GET",
            "header": [
                {"key": "Content-Type", "value": "application/json"},
                {"key": "Authorization", "value": "Bearer {{token}}", "disabled": True},
            ],
            "url": {
                "raw": "{{" + base_url_var + "}}" + path,
                "host": ["{{" + base_url_var + "}}"],
                "path": path_segments(path),
            },
            "description": f"Evidence: {api.get('evidence', '')}; Controller: {api.get('controller', '')}.{api.get('handler', '')}",
        },
        "event": [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "pm.test('status is 2xx', function () {",
                        "  pm.expect(pm.response.code).to.be.within(200, 299);",
                        "});",
                        "pm.test('response time is acceptable', function () {",
                        "  pm.expect(pm.response.responseTime).to.be.below(3000);",
                        "});",
                    ],
                },
            }
        ],
    }
    if method in {"POST", "PUT", "PATCH", "ANY"}:
        item["request"]["body"] = {"mode": "raw", "raw": sample_body(api), "options": {"raw": {"language": "json"}}}
    return item


def build_collection(impact: Dict[str, Any], base_url_var: str) -> Dict[str, Any]:
    source = impact.get("source", {})
    apis = impact.get("apis", [])
    safe_name = re.sub(r"[^\w.-]+", "-", str(source.get("repo") or "java-spring-pr"))
    name = f"{safe_name} PR {source.get('pr_number') or source.get('head_ref') or 'compare'} impact APIs"
    return {
        "info": {
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Generated from codediff-test-skill impact analysis. Complete auth, data, and assertions manually.",
        },
        "variable": [
            {"key": base_url_var, "value": "http://localhost:8080"},
            {"key": "token", "value": ""},
        ],
        "item": [build_item(api, base_url_var) for api in apis],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Postman collection from impact JSON")
    parser.add_argument("--impact-json", required=True)
    parser.add_argument("--output", "-o", default="postman_collection.json")
    parser.add_argument("--base-url-var", default="base_url")
    args = parser.parse_args()
    impact = load(Path(args.impact_json))
    collection = build_collection(impact, args.base_url_var)
    Path(args.output).write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} with {len(collection['item'])} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
