from __future__ import annotations


COST_LINE_FIELDS = [
    {"key": "material_cost", "label": "재료비", "type": "number", "min_value": 0.0, "step": 1.0},
    {"key": "process_cost", "label": "공정비", "type": "number", "min_value": 0.0, "step": 1.0},
    {"key": "defect_rate_pct", "label": "불량률(%)", "type": "number", "min_value": 0.0, "step": 0.1},
]
