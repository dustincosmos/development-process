from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


QUALITY_DEFAULT_KEYS = {
    *(f"spec_location_{idx}" for idx in range(1, 5)),
    *(f"spec_value_{idx}" for idx in range(1, 5)),
    *(f"appearance_item_{idx}" for idx in range(1, 5)),
    *(f"appearance_position_{idx}" for idx in range(1, 5)),
    "appearance_items",
    "appearance_positions",
}


def parse_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return deepcopy(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return deepcopy(parsed) if isinstance(parsed, dict) else {}


def quality_defaults_from_requirement(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in detail.items()
        if key in QUALITY_DEFAULT_KEYS and value not in (None, "", [], {})
    }


def apply_previous_quality_defaults(
    detail: dict[str, Any],
    previous_detail: dict[str, Any],
    *,
    source_order_id: int,
    source_order_code: str,
) -> dict[str, Any]:
    merged = deepcopy(detail)
    for key, value in quality_defaults_from_requirement(previous_detail).items():
        merged.setdefault(key, value)
    merged["_quality_default_source_type"] = "requirement"
    merged["_quality_default_source_id"] = int(source_order_id)
    merged["_quality_default_source_code"] = str(source_order_code)
    return merged


def requirement_plan(detail: dict[str, Any]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for idx, slot in enumerate(("A", "B", "C"), start=1):
        name = str(detail.get(f"spec_location_{idx}") or "").strip()
        spec = str(detail.get(f"spec_value_{idx}") or "").strip()
        if not name and not spec:
            continue
        plan.append(
            {
                "check_id": f"DIM-{slot}",
                "category": "dimension",
                "name": name or f"{slot} 측정부위",
                "spec": spec,
                "timings": ["immediate", "24h"],
                "repeat_count": 8,
                "required": True,
            }
        )
    return plan


def apply_plan_defaults_to_instruction(
    detail: dict[str, Any],
    plan: list[dict[str, Any]],
    *,
    source_instruction_id: int,
    source_instruction_code: str,
) -> dict[str, Any]:
    merged = deepcopy(detail)
    for item in plan:
        check_id = str(item.get("check_id") or "")
        slot = check_id.removeprefix("DIM-")
        if slot not in {"A", "B", "C"}:
            continue
        if not str(merged.get(f"measurement_title_{slot}") or "").strip():
            merged[f"measurement_title_{slot}"] = str(item.get("name") or "")
        if not str(merged.get(f"measurement_spec_{slot}") or "").strip():
            merged[f"measurement_spec_{slot}"] = str(item.get("spec") or "")
    merged["_inspection_plan_default_source"] = {
        "type": "instruction",
        "instruction_id": int(source_instruction_id),
        "instruction_code": str(source_instruction_code),
    }
    return merged


def ensure_instruction_plan(
    instruction_detail: dict[str, Any],
    requirement_detail: dict[str, Any],
    *,
    plan_version: int,
    source_order_id: int,
    source_order_code: str,
) -> dict[str, Any]:
    detail = deepcopy(instruction_detail)
    requirement_items = {item["check_id"]: item for item in requirement_plan(requirement_detail)}
    existing_plan = detail.get("inspection_plan")
    existing_items = {
        str(item.get("check_id")): item
        for item in existing_plan
        if isinstance(existing_plan, list) and isinstance(item, dict) and item.get("check_id")
    } if isinstance(existing_plan, list) else {}

    plan: list[dict[str, Any]] = []
    for idx, slot in enumerate(("A", "B", "C"), start=1):
        check_id = f"DIM-{slot}"
        fallback = existing_items.get(check_id) or requirement_items.get(check_id) or {}
        name = str(
            detail.get(f"measurement_title_{slot}")
            or fallback.get("name")
            or requirement_detail.get(f"spec_location_{idx}")
            or ""
        ).strip()
        spec = str(
            detail.get(f"measurement_spec_{slot}")
            or fallback.get("spec")
            or requirement_detail.get(f"spec_value_{idx}")
            or ""
        ).strip()
        if not name and not spec:
            continue
        detail[f"measurement_title_{slot}"] = name or f"{slot} 측정부위"
        detail[f"measurement_spec_{slot}"] = spec
        plan.append(
            {
                "check_id": check_id,
                "category": "dimension",
                "name": name or f"{slot} 측정부위",
                "spec": spec,
                "timings": list(fallback.get("timings") or ["immediate", "24h"]),
                "repeat_count": int(fallback.get("repeat_count") or 8),
                "required": bool(fallback.get("required", True)),
            }
        )

    detail["inspection_plan"] = plan
    detail["plan_version"] = max(1, int(plan_version))
    default_source = detail.pop("_inspection_plan_default_source", None)
    detail["inspection_plan_source"] = default_source or {
        "type": "requirement",
        "order_id": int(source_order_id),
        "order_code": str(source_order_code),
    }
    changes: list[dict[str, str]] = []
    for item in plan:
        requirement_item = requirement_items.get(str(item["check_id"]), {})
        for field in ("name", "spec"):
            before = str(requirement_item.get(field) or "").strip()
            after = str(item.get(field) or "").strip()
            if before != after:
                changes.append(
                    {
                        "check_id": str(item["check_id"]),
                        "field": field,
                        "requirement_value": before,
                        "instruction_value": after,
                    }
                )
    detail["inspection_plan_changes"] = changes
    return detail


def inspection_plan_from_details(
    instruction_detail: dict[str, Any],
    requirement_detail: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    plan = instruction_detail.get("inspection_plan")
    if isinstance(plan, list) and all(isinstance(item, dict) for item in plan):
        return deepcopy(plan)
    return requirement_plan(requirement_detail or instruction_detail)


def results_by_check_id(
    legacy_results: dict[str, Any],
    plan: list[dict[str, Any]],
    *,
    timing: str,
) -> list[dict[str, Any]]:
    prefix = "즉시" if timing == "immediate" else "24H"
    rows: list[dict[str, Any]] = []
    for item in plan:
        check_id = str(item.get("check_id") or "")
        slot = check_id.removeprefix("DIM-")
        values = [
            str(legacy_results.get(f"{prefix}_{slot}_{idx}") or "").strip()
            for idx in range(1, int(item.get("repeat_count") or 8) + 1)
        ]
        rows.append(
            {
                "check_id": check_id,
                "timing": timing,
                "values": values,
            }
        )
    return rows


def add_check_id_results(
    legacy_results: dict[str, Any],
    plan: list[dict[str, Any]],
    *,
    timing: str,
) -> dict[str, Any]:
    result = deepcopy(legacy_results)
    result["plan_results"] = results_by_check_id(result, plan, timing=timing)
    return result


def required_result_issues(
    plan: list[dict[str, Any]],
    immediate_results: dict[str, Any],
    after_24h_results: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    result_sources = {"immediate": immediate_results, "24h": after_24h_results}
    for item in plan:
        if not item.get("required", True):
            continue
        check_id = str(item.get("check_id") or "")
        name = str(item.get("name") or check_id)
        slot = check_id.removeprefix("DIM-")
        for timing in item.get("timings") or []:
            source = result_sources.get(str(timing), {})
            prefix = "즉시" if timing == "immediate" else "24H"
            has_value = any(
                str(source.get(f"{prefix}_{slot}_{idx}") or "").strip()
                for idx in range(1, int(item.get("repeat_count") or 8) + 1)
            )
            if not has_value:
                timing_label = "즉시" if timing == "immediate" else "24시간 후"
                issues.append(f"{name}의 {timing_label} 측정값")
    return issues
