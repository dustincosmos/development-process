from __future__ import annotations


CUSTOMER_REQUIREMENT_COMMON_FIELDS = [
    {"key": "target_due_date", "label": "완료일", "type": "date"},
    {"key": "required_sample_qty", "label": "필요 샘플 수", "type": "number", "min_value": 1, "step": 1},
    {"key": "milestone_name", "label": "개발 마일스톤", "type": "select"},
    {"key": "experiment_goal", "label": "고객 요구 요약", "type": "text"},
]


INJECTION_INSTRUCTION_CORE_FIELDS = [
    {"key": "mold_label", "label": "금형", "type": "select"},
    {"key": "raw_material_label", "label": "원료", "type": "select"},
    {"key": "mb_nuance", "label": "지시 확정 뉴앙스", "type": "text"},
    {"key": "mb_expected_receipt_date", "label": "지시 납기일", "type": "date"},
]
