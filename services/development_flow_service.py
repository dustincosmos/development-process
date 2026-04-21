from __future__ import annotations

from typing import Any

import pandas as pd


def infer_process_type(item_row: pd.Series | None, process_options: list[str]) -> str:
    if item_row is None:
        return ""
    item_type = str(item_row.get("item_type") or "")
    process_type = str(item_row.get("process_type") or "")
    if process_type in process_options:
        return process_type
    # Legacy fallback for older items saved before process_type was mandatory.
    if "사출" in item_type:
        return "사출"
    if "인쇄" in item_type:
        return "인쇄"
    if "사상" in item_type:
        return "사상"
    if "조립" in item_type:
        return "조립"
    return "후가공"


def validate_requirement_save(
    project_label: str,
    selected_item_id: int | None,
    process_type: str,
    detail_payload: dict[str, Any],
) -> str | None:
    if not project_label or not selected_item_id:
        return "프로젝트와 공정품을 먼저 선택해 주세요."
    if not process_type:
        return "선택한 공정품에 공정 정보가 없습니다. 공정품 정보에서 공정을 먼저 지정해 주세요."
    if process_type in ["사출", "후가공", "인쇄", "사상"] and detail_payload.get("color_required"):
        if not str(detail_payload.get("color_nuance", "")).strip():
            return "색상 요구가 있으면 색상 뉴앙스를 입력해 주세요."
    if process_type in ("후가공", "사상") and detail_payload.get("execution_mode") == "실험":
        predecessor_links = detail_payload.get("predecessor_links", []) or []
        for link in predecessor_links:
            source_mode = str(link.get("source_mode") or "")
            if source_mode == "기존실험요구" and not link.get("source_order_id"):
                return f"{process_type} 실험은 각 전공정품의 실험요구를 선택해 주세요."
            if source_mode == "재고품" and not link.get("source_sample_id"):
                return f"{process_type} 실험은 각 전공정품의 재고품을 선택해 주세요."
    return None


def filter_instruction_samples(
    samples_df: pd.DataFrame,
    project_code: str,
    item_id: int | None,
    order_code: str | None,
) -> pd.DataFrame:
    filtered = samples_df.copy()
    if project_code:
        filtered = filtered[filtered["project_code"] == project_code]
    if item_id:
        filtered = filtered[filtered["item_id"] == item_id]
    if order_code:
        filtered = filtered[filtered["order_code"] == order_code]
    return filtered


def build_instruction_summary_labels(order_row: pd.Series, process_type: str) -> list[tuple[str, str]]:
    labels: list[tuple[str, str]] = [("공정", process_type or "-")]
    milestone_name = str(order_row.get("milestone_name") or "")
    if milestone_name:
        labels.append(("마일스톤", milestone_name))
    labels.extend(
        [
            ("기준도면", str(order_row.get("base_drawing_revision") or "-")),
            ("도면입수", str(order_row.get("drawing_receipt_status") or "-")),
            ("완료일", str(order_row.get("target_due_date") or "-")),
        ]
    )
    return labels


def validate_instruction_save(
    selected_order_id: int | None,
    process_type: str,
    mold_label: str,
    raw_material_label: str,
    film_label: str,
    order_detail: dict[str, Any],
    mb_nuance: str,
    mb_supplier_name: str,
    mb_expected_receipt_date: str | None,
    mb_ratio_count: int,
    samples_df: pd.DataFrame,
    base_order_code: str,
    sample_seq: int,
    sample_code: str,
    selected_row: pd.Series | None,
) -> str | None:
    if not selected_order_id:
        return "고객요구를 먼저 선택해 주세요."
    if process_type == "사출" and (not mold_label or not raw_material_label):
        return "사출 실험지시는 금형과 원재료를 모두 선택해 주세요."
    if process_type == "인쇄" and not film_label:
        return "인쇄 실험지시는 원화를 선택해 주세요."
    if process_type == "사출" and order_detail.get("color_required"):
        if not mb_nuance.strip() or not mb_supplier_name.strip() or not mb_expected_receipt_date:
            return "사출 색상 지시에는 확정 뉴앙스, 업체, 납기일을 입력해 주세요."
        if mb_ratio_count <= 0:
            return "사출 색상 지시에는 MB 농도를 1개 이상 입력해 주세요."

    duplicate_samples = samples_df[
        (samples_df["order_code"] == base_order_code)
        & (samples_df["sample_seq"] == int(sample_seq))
    ]
    if selected_row is not None:
        duplicate_samples = duplicate_samples[duplicate_samples["sample_id"] != int(selected_row["sample_id"])]
    if not duplicate_samples.empty:
        return f"같은 고객요구에 샘플 순번 {int(sample_seq)}가 이미 있습니다. 다른 순번을 선택해 주세요."

    duplicate_code_rows = samples_df[samples_df["sample_code"] == sample_code]
    if selected_row is not None:
        duplicate_code_rows = duplicate_code_rows[duplicate_code_rows["sample_id"] != int(selected_row["sample_id"])]
    if not duplicate_code_rows.empty:
        return f"실험지시 코드 {sample_code}가 이미 있습니다. 샘플 순번을 변경해 주세요."

    return None
