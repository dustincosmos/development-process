from __future__ import annotations

import pandas as pd

from db import development_flow_repository
from domain.schemas import (
    ExperimentInstructionPayload,
    ExperimentOrderPayload,
    ExperimentSamplePayload,
    FinalReviewPayload,
    OpReviewPayload,
    QualityReviewPayload,
)
from services import operations_service
from services.reference_data_service import get_products


def list_project_options() -> list[tuple[str, int]]:
    return development_flow_repository.list_project_options()


def get_project_by_code(project_code: str):
    return development_flow_repository.get_project_by_code(project_code)


def list_item_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return development_flow_repository.list_item_options_for_project(project_code)


def list_project_item_tree_options(project_code: str, product_id: int | None = None) -> list[tuple[str, int]]:
    return development_flow_repository.list_project_item_tree_options(project_code, product_id)


def get_item_row(item_id: int | None):
    return development_flow_repository.get_item_row(item_id)


def get_meta_requirement_row(meta_requirement_id: int | None):
    return development_flow_repository.get_meta_requirement_row(meta_requirement_id)


def list_meta_requirements_for_context(project_id: int | None, product_id: int | None, tree_mode: str | None):
    return development_flow_repository.list_meta_requirements_for_context(project_id, product_id, tree_mode)


def list_meta_requirement_lines(meta_requirement_id: int | None):
    return development_flow_repository.list_meta_requirement_lines(meta_requirement_id)


def list_meta_requirement_line_links() -> pd.DataFrame:
    return development_flow_repository.list_meta_requirement_line_links()


def list_requirement_ledger_rows() -> pd.DataFrame:
    return development_flow_repository.list_requirement_ledger_rows()


def get_requirement_line_context(requirement_row_id: int | None):
    return development_flow_repository.get_requirement_line_context(requirement_row_id)


def _normalize_scope_to_process(scope: str | None, line_process_type: str | None) -> str:
    scope_text = str(scope or "").strip()
    if scope_text == "사출":
        return "사출"
    if scope_text == "조립":
        return "조립"
    if scope_text in {"인쇄", "후가공"}:
        return scope_text
    if scope_text == "공정품":
        return str(line_process_type or "").strip()
    return str(line_process_type or "").strip()


def get_requirement_jump_context(requirement_row_id: int | None, scope: str | None) -> dict[str, object]:
    line_row = get_requirement_line_context(requirement_row_id)
    if line_row is None:
        return {}
    line_process_type = str(line_row["process_type"]) if "process_type" in line_row.keys() and pd.notna(line_row["process_type"]) else ""
    target_process_type = _normalize_scope_to_process(scope, line_process_type)
    orders_df = list_experiment_orders()
    instructions_df = list_experiment_instructions()
    requirement_order_id = None
    requirement_instruction_id = None
    linked_order_id = (
        int(line_row["linked_experiment_order_id"])
        if "linked_experiment_order_id" in line_row.keys() and pd.notna(line_row["linked_experiment_order_id"])
        else None
    )
    if not orders_df.empty:
        order_match = orders_df[
            (pd.to_numeric(orders_df["meta_line_id"], errors="coerce") == int(line_row["meta_line_id"]))
            & (orders_df["process_type"] == target_process_type)
        ].sort_values("experiment_order_id", ascending=False)
        if not order_match.empty:
            requirement_order_id = int(order_match.iloc[0]["experiment_order_id"])
        elif linked_order_id:
            linked_order_match = orders_df[
                pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == int(linked_order_id)
            ].sort_values("experiment_order_id", ascending=False)
            if not linked_order_match.empty:
                linked_order_row = linked_order_match.iloc[0]
                linked_order_process = str(linked_order_row["process_type"] or "").strip()
                if linked_order_process == target_process_type:
                    requirement_order_id = int(linked_order_row["experiment_order_id"])
        if requirement_order_id and not instructions_df.empty:
            instruction_match = instructions_df[
                pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == requirement_order_id
            ].sort_values("experiment_instruction_id", ascending=False)
            if not instruction_match.empty:
                requirement_instruction_id = int(instruction_match.iloc[0]["experiment_instruction_id"])
    return {
        "requirement_row_id": int(line_row["meta_line_id"]),
        "meta_requirement_id": int(line_row["meta_requirement_id"]) if pd.notna(line_row["meta_requirement_id"]) else None,
        "project_id": int(line_row["project_id"]) if pd.notna(line_row["project_id"]) else None,
        "project_code": str(line_row["project_code"] or ""),
        "product_id": int(line_row["product_id"]) if pd.notna(line_row["product_id"]) else None,
        "item_id": int(line_row["item_id"]) if pd.notna(line_row["item_id"]) else None,
        "process_type": target_process_type,
        "order_id": requirement_order_id,
        "instruction_id": requirement_instruction_id,
    }


def list_integrated_board_rows(project_code: str | None = None) -> pd.DataFrame:
    ledger_df = list_requirement_ledger_rows()
    if ledger_df.empty:
        return ledger_df
    board_df = ledger_df.copy()
    if project_code:
        board_df = board_df[board_df["project_code"] == project_code].copy()
    if board_df.empty:
        return board_df
    orders_df = list_experiment_orders()
    if not orders_df.empty:
        normalized_orders = orders_df.copy()
        normalized_orders["meta_line_id"] = pd.to_numeric(normalized_orders["meta_line_id"], errors="coerce")
        normalized_orders["target_due_date"] = normalized_orders["target_due_date"].fillna("")
        normalized_orders = normalized_orders.sort_values(["meta_line_id", "experiment_order_id"], ascending=[True, False])
        latest_order_by_line = normalized_orders.dropna(subset=["meta_line_id"]).drop_duplicates(subset=["meta_line_id"], keep="first")
        latest_order_by_line = latest_order_by_line.rename(columns={
            "target_due_date": "요구 납기일",
            "status": "요구 상태",
            "order_code": "요구 코드",
            "experiment_order_id": "linked_order_id_actual",
        })
        board_df = board_df.merge(
            latest_order_by_line[["meta_line_id", "요구 납기일", "요구 상태", "요구 코드", "linked_order_id_actual"]],
            on="meta_line_id",
            how="left",
        )
    else:
        board_df["요구 납기일"] = ""
        board_df["요구 상태"] = ""
        board_df["요구 코드"] = ""
        board_df["linked_order_id_actual"] = None

    def _status(linked_value, process_type: str, target: str) -> str:
        if target == "사출":
            return "생성됨" if pd.notna(linked_value) and process_type == "사출" else ("대상" if process_type == "사출" else "-")
        if target == "조립":
            return "생성됨" if pd.notna(linked_value) and process_type == "조립" else ("대상" if process_type == "조립" else "-")
        if target == "인쇄":
            return "생성됨" if pd.notna(linked_value) and process_type == "인쇄" else ("대상" if process_type == "인쇄" else "-")
        if target == "후가공":
            return "생성됨" if pd.notna(linked_value) and process_type in {"후가공", "사상"} else ("대상" if process_type in {"후가공", "사상"} else "-")
        return "생성됨" if pd.notna(linked_value) and process_type not in {"사출", "조립", "인쇄", "후가공", "사상"} else ("대상" if process_type not in {"사출", "조립", "인쇄", "후가공", "사상"} else "-")

    board_df["사출 지시 상태"] = board_df.apply(lambda row: _status(row.get("linked_injection_instruction_id"), str(row.get("process_type") or ""), "사출"), axis=1)
    board_df["공정품 지시 상태"] = board_df.apply(lambda row: _status(row.get("linked_process_instruction_id"), str(row.get("process_type") or ""), "공정품"), axis=1)
    board_df["조립 지시 상태"] = board_df.apply(lambda row: _status(row.get("linked_assembly_instruction_id"), str(row.get("process_type") or ""), "조립"), axis=1)
    board_df["인쇄 지시 상태"] = board_df.apply(lambda row: _status(row.get("linked_print_instruction_id"), str(row.get("process_type") or ""), "인쇄"), axis=1)
    board_df["후가공 지시 상태"] = board_df.apply(lambda row: _status(row.get("linked_postprocess_instruction_id"), str(row.get("process_type") or ""), "후가공"), axis=1)

    def _overall_status(row) -> str:
        if any(pd.notna(row.get(col)) for col in [
            "linked_injection_instruction_id",
            "linked_process_instruction_id",
            "linked_assembly_instruction_id",
            "linked_print_instruction_id",
            "linked_postprocess_instruction_id",
        ]):
            return "지시생성"
        if pd.notna(row.get("linked_experiment_order_id")):
            return "요구등록"
        return "미생성"

    board_df["전체 상태"] = board_df.apply(_overall_status, axis=1)
    board_df["표시 상태"] = board_df.apply(
        lambda row: "지시생성"
        if row["전체 상태"] == "지시생성"
        else ("요구등록" if pd.notna(row.get("linked_experiment_order_id")) else "미생성"),
        axis=1,
    )
    board_df["납기일"] = board_df["요구 납기일"].fillna("").astype(str)
    return board_df


def save_meta_requirement_lines(
    *,
    meta_requirement_id: int,
    root_item_id: int,
    tree_mode: str,
    selected_item_ids: list[int],
) -> None:
    development_flow_repository.save_meta_requirement_lines(
        meta_requirement_id=meta_requirement_id,
        root_item_id=root_item_id,
        tree_mode=tree_mode,
        selected_item_ids=selected_item_ids,
    )


def save_meta_requirement_line_link(
    *,
    meta_requirement_id: int,
    meta_line_id: int,
    linked_experiment_order_id: int | None,
    linked_required_sample_qty: int | None,
) -> None:
    development_flow_repository.save_meta_requirement_line_link(
        meta_requirement_id=meta_requirement_id,
        meta_line_id=meta_line_id,
        linked_experiment_order_id=linked_experiment_order_id,
        linked_required_sample_qty=linked_required_sample_qty,
    )


def list_order_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return development_flow_repository.list_order_options_for_project(project_code)


def list_mold_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return development_flow_repository.list_mold_options_for_project(project_code)


def list_film_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return development_flow_repository.list_film_options_for_project(project_code)


def list_raw_material_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return development_flow_repository.list_raw_material_options_for_project(project_code)


def list_items() -> pd.DataFrame:
    return development_flow_repository.list_items()


def get_current_product_drawing_for_item(item_id: int) -> dict | None:
    return development_flow_repository.get_current_product_drawing_for_item(item_id)


def list_product_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_products()
    if df.empty or not project_code:
        return []
    filtered = df[df["project_code"] == project_code]
    return [(f"{row['product_code']} | {row['product_name']}", int(row["product_id"])) for _, row in filtered.iterrows()]


def list_experiment_orders() -> pd.DataFrame:
    return development_flow_repository.list_experiment_orders()


def list_experiment_instructions() -> pd.DataFrame:
    return development_flow_repository.list_experiment_instructions()


def list_experiment_samples() -> pd.DataFrame:
    return development_flow_repository.list_experiment_samples()


def list_sample_workflow() -> pd.DataFrame:
    return development_flow_repository.list_sample_workflow()


def list_mb_requests() -> pd.DataFrame:
    return development_flow_repository.list_mb_requests()


def list_mold_dispatch_orders() -> pd.DataFrame:
    return development_flow_repository.list_mold_dispatch_orders()


def delete_experiment_order(experiment_order_id: int) -> tuple[bool, str]:
    ok, message = development_flow_repository.delete_experiment_order(experiment_order_id)
    if ok:
        operations_service.prepare_wms(current_user_name="system")
    return ok, message


def update_experiment_order_status(experiment_order_id: int, status: str) -> tuple[bool, str]:
    ok, message = development_flow_repository.update_experiment_order_status(experiment_order_id, status)
    if ok:
        operations_service.prepare_wms(current_user_name="system")
    return ok, message


def get_experiment_order_usage(experiment_order_id: int) -> dict[str, bool]:
    return development_flow_repository.get_experiment_order_usage(experiment_order_id)


def save_experiment_order(
    selected_row: pd.Series | None,
    *,
    payload: ExperimentOrderPayload,
    current_user_name: str,
) -> tuple[int, str, int | None]:
    result = development_flow_repository.save_experiment_order(
        selected_row,
        payload=payload,
        current_user_name=current_user_name,
    )
    operations_service.prepare_wms(current_user_name=current_user_name)
    operations_service.sync_customer_dispatch_orders(current_user_name=current_user_name)
    return result


def save_experiment_instruction(
    selected_row: pd.Series | None,
    *,
    payload: ExperimentInstructionPayload,
    current_user_name: str,
) -> tuple[int, str, str | None]:
    result = development_flow_repository.save_experiment_instruction(
        selected_row,
        payload=payload,
        current_user_name=current_user_name,
    )
    operations_service.prepare_wms(current_user_name=current_user_name)
    return result


def delete_experiment_instruction(experiment_instruction_id: int) -> tuple[bool, str]:
    result = development_flow_repository.delete_experiment_instruction(experiment_instruction_id)
    if result[0]:
        operations_service.prepare_wms(current_user_name="system")
    return result


def delete_experiment_sample(sample_id: int) -> tuple[bool, str]:
    return development_flow_repository.delete_experiment_sample(sample_id)


def save_experiment_sample(
    selected_row: pd.Series | None,
    *,
    payload: ExperimentSamplePayload,
    linked_mb_request_row: pd.Series | None,
    linked_mold_dispatch_row: pd.Series | None,
    project_molds: list[tuple[str, int]],
    project_films: list[tuple[str, int]],
    current_user_name: str,
) -> int:
    return development_flow_repository.save_experiment_sample(
        selected_row,
        payload=payload,
        linked_mb_request_row=linked_mb_request_row,
        linked_mold_dispatch_row=linked_mold_dispatch_row,
        project_molds=project_molds,
        project_films=project_films,
        current_user_name=current_user_name,
    )


def save_op_review(*, payload: OpReviewPayload, current_user_name: str) -> None:
    development_flow_repository.save_op_review(payload=payload, current_user_name=current_user_name)


def save_quality_review(*, payload: QualityReviewPayload, current_user_name: str) -> None:
    development_flow_repository.save_quality_review(payload=payload, current_user_name=current_user_name)


def save_final_review(*, payload: FinalReviewPayload, current_user_name: str) -> None:
    development_flow_repository.save_final_review(payload=payload, current_user_name=current_user_name)
    operations_service.sync_customer_dispatch_for_sample(
        sample_id=int(payload["sample_id"]),
        current_user_name=current_user_name,
    )
