from __future__ import annotations


STAGE_SEQUENCE = [
    "계획",
    "지시",
    "실행",
    "품질검토",
    "최종검토",
    "원가시뮬레이션",
]


FIELD_OWNERS = {
    "milestone_name": "계획",
    "target_due_date": "계획",
    "requirement_detail_json": "계획",
    "base_drawing_revision": "지시",
    "drawing_receipt_status": "지시",
    "mold_id": "지시",
    "raw_material_id": "지시",
    "mb_request_id": "지시",
    "expected_receipt_date": "지시",
    "raw_material_used_g": "실행",
    "mb_used_g": "실행",
    "runner_weight": "실행",
    "product_weight": "실행",
    "quality_comment": "품질검토",
    "approval_status": "최종검토",
    "ct_sec": "원가시뮬레이션",
    "daily_rate": "원가시뮬레이션",
    "management_rate_pct": "원가시뮬레이션",
    "defect_rate_pct": "원가시뮬레이션",
}


DEFAULT_VALUE_FLOW = {
    "원가시뮬레이션": ["계획", "지시", "실행", "품질검토", "최종검토"],
    "실행": ["계획", "지시"],
    "품질검토": ["계획", "지시", "실행"],
    "최종검토": ["계획", "지시", "실행", "품질검토"],
}
