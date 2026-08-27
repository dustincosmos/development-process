from __future__ import annotations

import pandas as pd
import streamlit as st

from db.runtime import latest_rows_by_code, query_df
from domain.constants import EXPERIMENT_PROCESS_OPTIONS
from services.development_flow_service import infer_process_type


@st.cache_data(show_spinner=False)
def get_projects() -> pd.DataFrame:
    return query_df(
        """
        SELECT project_id, project_code, customer_name, product_name, development_type, launch_date, packaging_date,
               production_plan_date, new_product_test_due_date, standard_due_date, t0_date, t1_date,
               sales_owner, developer_owner, mold_vendor_name, supervisor_name, status, notes
        FROM development_projects
        ORDER BY project_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_products() -> pd.DataFrame:
    return query_df(
        """
        SELECT pr.product_id, pr.project_id, p.project_code, p.product_name AS project_name,
               pr.product_code, pr.product_name, pr.root_item_id, pr.linked_item_id,
               i.item_code AS linked_item_code, i.item_name AS linked_item_name, pr.notes
        FROM products pr
        JOIN development_projects p ON p.project_id = pr.project_id
        LEFT JOIN items i ON i.item_id = COALESCE(pr.linked_item_id, pr.root_item_id)
        ORDER BY pr.product_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_product_drawings() -> pd.DataFrame:
    return query_df(
        """
        SELECT d.product_drawing_id, p.project_code, p.product_name, d.drawing_no, d.drawing_name,
               d.revision_no, d.file_note, d.file_path, d.is_current, d.notes
        FROM product_drawings d
        JOIN development_projects p ON p.project_id = d.project_id
        ORDER BY d.drawing_no, d.is_current DESC, d.product_drawing_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_mold_drawings() -> pd.DataFrame:
    return query_df(
        """
        SELECT md.mold_drawing_id, md.product_drawing_id, p.project_code, p.product_name, md.mold_drawing_no,
               md.revision_no, md.cavity_layout, md.design_priority, md.file_path,
               pd.drawing_no AS product_drawing_no, md.notes
        FROM mold_drawings md
        JOIN development_projects p ON p.project_id = md.project_id
        LEFT JOIN product_drawings pd ON pd.product_drawing_id = md.product_drawing_id
        ORDER BY md.mold_drawing_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_molds() -> pd.DataFrame:
    return query_df(
        """
        SELECT m.mold_id, p.project_code, p.product_name, m.mold_code, m.mold_name,
               m.cavity, m.vendor_name, m.status, md.mold_drawing_no, m.notes
        FROM molds m
        JOIN development_projects p ON p.project_id = m.project_id
        LEFT JOIN mold_drawings md ON md.mold_drawing_id = m.mold_drawing_id
        ORDER BY m.mold_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_mold_dispatch_orders() -> pd.DataFrame:
    return query_df(
        """
        SELECT md.mold_dispatch_order_id, md.experiment_order_id, md.dispatch_code, p.project_code, i.item_id, i.item_code, i.item_name,
               eo.order_code, eo.target_due_date, m.mold_code, m.mold_name, md.dispatch_reason, md.sample_request_date,
               latest_ei.instruction_code, latest_ei.requested_finish_date,
               md.dispatch_date, md.receipt_date, md.modification_note, md.status
        FROM mold_dispatch_orders md
        JOIN development_projects p ON p.project_id = md.project_id
        JOIN items i ON i.item_id = md.item_id
        JOIN experiment_orders eo ON eo.experiment_order_id = md.experiment_order_id
        LEFT JOIN molds m ON m.mold_id = md.mold_id
        LEFT JOIN (
            SELECT ei1.experiment_order_id, ei1.instruction_code, ei1.requested_finish_date
            FROM experiment_instructions ei1
            JOIN (
                SELECT experiment_order_id, MAX(experiment_instruction_id) AS max_instruction_id
                FROM experiment_instructions
                GROUP BY experiment_order_id
            ) latest
              ON latest.experiment_order_id = ei1.experiment_order_id
             AND latest.max_instruction_id = ei1.experiment_instruction_id
        ) latest_ei ON latest_ei.experiment_order_id = md.experiment_order_id
        ORDER BY md.mold_dispatch_order_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_document_revision_orders() -> pd.DataFrame:
    return query_df(
        """
        SELECT dro.document_revision_order_id, dro.experiment_order_id, dro.project_id, p.project_code,
               dro.item_id, i.item_code, i.item_name, eo.order_code, dro.document_type,
               dro.base_document_id, dro.request_code, dro.request_reason,
               dro.expected_receipt_date, dro.receipt_date, dro.status
        FROM document_revision_orders dro
        JOIN development_projects p ON p.project_id = dro.project_id
        JOIN items i ON i.item_id = dro.item_id
        JOIN experiment_orders eo ON eo.experiment_order_id = dro.experiment_order_id
        ORDER BY dro.document_revision_order_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_postprocess_item_moves() -> pd.DataFrame:
    return query_df(
        """
        SELECT pm.postprocess_move_id, pm.move_code, pm.sample_id, p.project_id, p.project_code,
               pr.product_id, pr.product_code, pr.product_name,
               i.item_id, i.item_code, i.item_name, COALESCE(pm.process_type, i.process_type) AS process_type,
               pm.actual_item_id, ai.item_code AS actual_item_code, ai.item_name AS actual_item_name,
               s.sample_code,
               eo.order_code AS source_order_code, eo.status AS source_order_status,
               ei.instruction_code AS source_instruction_code, ei.status AS source_instruction_status,
               s.status AS sample_status, s.experiment_date,
               qr.quality_review_date, fr.final_review_date, fr.approval_status,
               COALESCE(pm.partner_name, pm.vendor_name, '내부') AS partner_name,
               pm.vendor_name, pm.execution_mode, pm.wms_kind, pm.source_type, pm.source_order_id, pm.source_instruction_id,
               pm.child_dispatch_note, pm.dispatch_date, pm.expected_receipt_date, pm.receipt_date,
               pm.from_location, pm.to_location,
               pm.requested_qty, pm.dispatch_qty, pm.receipt_qty,
               pm.receipt_note, pm.unit_cost, pm.uph, pm.defect_rate, pm.moq,
               pm.inventory_status, pm.status
        FROM postprocess_item_moves pm
        JOIN development_projects p ON p.project_id = pm.project_id
        JOIN items i ON i.item_id = pm.item_id
        LEFT JOIN items ai ON ai.item_id = COALESCE(pm.actual_item_id, pm.item_id)
        LEFT JOIN products pr ON pr.product_id = COALESCE(pm.product_id, i.product_id)
        LEFT JOIN experiment_samples s ON s.sample_id = pm.sample_id
        LEFT JOIN experiment_orders eo ON eo.experiment_order_id = pm.source_order_id
        LEFT JOIN experiment_instructions ei ON ei.experiment_instruction_id = pm.source_instruction_id
        LEFT JOIN sample_quality_reviews qr ON qr.sample_id = s.sample_id
        LEFT JOIN sample_final_reviews fr ON fr.sample_id = s.sample_id
        ORDER BY pm.postprocess_move_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_sample_inventory() -> pd.DataFrame:
    return query_df(
        """
        SELECT inv.sample_id, inv.project_id, p.project_code,
               pr.product_id, pr.product_code, pr.product_name,
               inv.item_id, i.item_code, i.item_name, i.process_type,
               s.sample_code, s.sample_name,
               inv.qty_on_hand, inv.qty_reserved,
               (inv.qty_on_hand - inv.qty_reserved) AS qty_available,
               inv.current_location, inv.partner_name, inv.status, inv.updated_at
        FROM sample_inventory inv
        JOIN development_projects p ON p.project_id = inv.project_id
        JOIN items i ON i.item_id = inv.item_id
        LEFT JOIN products pr ON pr.product_id = i.product_id
        LEFT JOIN experiment_samples s ON s.sample_id = inv.sample_id
        ORDER BY p.project_code, i.item_code, inv.sample_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_print_films() -> pd.DataFrame:
    return query_df(
        """
        SELECT f.print_film_id, p.project_code, p.product_name, f.film_code, f.film_name,
               f.artwork_type, f.revision_no, f.related_item_name, f.status, f.file_path, f.notes, f.is_current
        FROM print_films f
        JOIN development_projects p ON p.project_id = f.project_id
        ORDER BY f.film_code, f.is_current DESC, f.print_film_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_items() -> pd.DataFrame:
    return query_df(
        """
        SELECT i.item_id, p.project_code, p.product_name, i.product_id, pr.product_code, pr.product_name AS linked_product_name,
               i.item_code, i.item_name, i.item_class,
               i.item_type, i.process_type, i.product_drawing_id, i.base_print_film_id, i.primary_mold_id,
               i.base_revision_no, i.base_material_label, i.base_color_label,
               pd.drawing_no AS product_drawing_no, pd.revision_no AS product_drawing_revision_no,
               pf.film_code AS base_film_code, pf.film_name AS base_film_name, pf.revision_no AS base_film_revision_no,
               m.mold_code AS primary_mold_code,
               i.mb_note, i.notes
        FROM items i
        LEFT JOIN development_projects p ON p.project_id = i.project_id
        LEFT JOIN products pr ON pr.product_id = i.product_id
        LEFT JOIN product_drawings pd ON pd.product_drawing_id = i.product_drawing_id
        LEFT JOIN print_films pf ON pf.print_film_id = i.base_print_film_id
        LEFT JOIN molds m ON m.mold_id = i.primary_mold_id
        ORDER BY i.item_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_raw_materials() -> pd.DataFrame:
    return query_df(
        """
        SELECT raw_material_id, material_code, material_name, material_type, supplier_name, status, notes
        FROM raw_materials
        ORDER BY raw_material_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_sub_materials() -> pd.DataFrame:
    return query_df(
        """
        SELECT sub_material_id, material_code, material_name, material_type, supplier_name,
               backing_diameter, backing_thickness, backing_material_type, label_film_id,
               status, notes
        FROM sub_materials
        ORDER BY sub_material_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_mb_materials() -> pd.DataFrame:
    return query_df(
        """
        SELECT mb_material_id, mb_code, mb_name, supplier_name, status, notes
        FROM mb_materials
        ORDER BY mb_material_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_mb_requests() -> pd.DataFrame:
    return query_df(
        """
        SELECT mr.mb_request_id, mr.experiment_order_id, mr.request_code, p.project_code, i.item_id, i.item_code, i.item_name,
               eo.order_code, mr.color_nuance, mr.color_sample_exists, mr.supplier_name, mr.consultation_note,
               mr.sample_sent, mr.sample_received, mr.expected_receipt_date, mr.purchase_requested, mr.status,
               latest_ei.instruction_code, latest_ei.requested_finish_date
        FROM mb_requests mr
        JOIN development_projects p ON p.project_id = mr.project_id
        JOIN items i ON i.item_id = mr.item_id
        JOIN experiment_orders eo ON eo.experiment_order_id = mr.experiment_order_id
        LEFT JOIN (
            SELECT ei1.experiment_order_id, ei1.instruction_code, ei1.requested_finish_date
            FROM experiment_instructions ei1
            JOIN (
                SELECT experiment_order_id, MAX(experiment_instruction_id) AS max_instruction_id
                FROM experiment_instructions
                GROUP BY experiment_order_id
            ) latest
              ON latest.experiment_order_id = ei1.experiment_order_id
             AND latest.max_instruction_id = ei1.experiment_instruction_id
        ) latest_ei ON latest_ei.experiment_order_id = mr.experiment_order_id
        ORDER BY mr.mb_request_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_mb_receipts() -> pd.DataFrame:
    return query_df(
        """
        SELECT rc.mb_receipt_id, mr.mb_request_id, mr.request_code, eo.order_code, p.project_code, i.item_code, i.item_name,
               mr.color_nuance, mr.supplier_name, rc.receipt_date, rc.receipt_qty, rc.lot_no, rc.receipt_note, rc.status
        FROM mb_receipts rc
        JOIN mb_requests mr ON mr.mb_request_id = rc.mb_request_id
        JOIN development_projects p ON p.project_id = mr.project_id
        JOIN items i ON i.item_id = mr.item_id
        JOIN experiment_orders eo ON eo.experiment_order_id = mr.experiment_order_id
        ORDER BY rc.mb_receipt_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_users() -> pd.DataFrame:
    return query_df(
        """
        SELECT u.user_id, u.login_id, u.user_name, u.role_code,
               GROUP_CONCAT(ur.role_code, ',') AS role_codes,
               GROUP_CONCAT(r.role_name, ', ') AS role_names,
               u.department, u.is_active, u.created_at
        FROM users u
        LEFT JOIN user_roles ur ON ur.user_id = u.user_id
        LEFT JOIN roles r ON r.role_code = ur.role_code
        GROUP BY u.user_id, u.login_id, u.user_name, u.role_code, u.department, u.is_active, u.created_at
        ORDER BY u.user_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_roles() -> pd.DataFrame:
    return query_df(
        """
        SELECT role_code, role_name, is_active
        FROM roles
        ORDER BY role_code
        """
    )


@st.cache_data(show_spinner=False)
def get_role_menu_permissions() -> pd.DataFrame:
    return query_df(
        """
        SELECT role_code, menu_group, menu_name, is_enabled, created_at
        FROM role_menu_permissions
        ORDER BY role_code, menu_group, menu_name
        """
    )


@st.cache_data(show_spinner=False)
def get_item_bom() -> pd.DataFrame:
    return query_df(
        """
        SELECT b.bom_id, b.project_id, b.parent_item_id, b.child_item_id, p.project_code,
               pi.item_code AS parent_item_code, pi.item_name AS parent_item_name,
               ci.item_code AS child_item_code, ci.item_name AS child_item_name,
               b.qty, b.qty_unit, b.notes
        FROM item_bom b
        JOIN development_projects p ON p.project_id = b.project_id
        JOIN items pi ON pi.item_id = b.parent_item_id
        JOIN items ci ON ci.item_id = b.child_item_id
        ORDER BY b.bom_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_experiment_orders() -> pd.DataFrame:
    return query_df(
        """
        SELECT eo.experiment_order_id, eo.meta_requirement_id, eo.meta_line_id, eo.project_id, eo.product_id, eo.order_code, p.project_code, i.item_id, i.item_code, i.item_name,
               eo.process_type, eo.requirement_date, eo.milestone_name, eo.base_drawing_revision, eo.drawing_receipt_status, eo.mold_pre_update, eo.mold_dispatch_required,
               eo.target_due_date, eo.milestone_due_date,
               eo.required_sample_qty, eo.experiment_goal, eo.success_criteria,
               eo.requested_by, eo.status, eo.request_notes,
               eo.requirement_checks_json, eo.requirement_detail_json
        FROM experiment_orders eo
        JOIN development_projects p ON p.project_id = eo.project_id
        JOIN items i ON i.item_id = eo.item_id
        ORDER BY eo.experiment_order_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_experiment_samples() -> pd.DataFrame:
    return query_df(
        """
        SELECT s.sample_id, s.experiment_instruction_id, ei.instruction_code, eo.order_code, eo.product_id, p.project_code, i.item_code, i.item_name, s.sample_code,
               s.sample_seq, s.sample_name, s.experiment_date, s.variation_note, s.used_mold_id, s.used_film_id,
               m.mold_code, f.film_code, mr.request_code AS mb_request_code,
               s.status,
               eo.requirement_date, ei.instruction_date, eo.milestone_name, eo.target_due_date,
               eo.base_drawing_revision, eo.drawing_receipt_status, eo.mold_pre_update,
               s.customer_delivery_date, s.customer_result_date, s.customer_result, s.customer_result_notes,
               s.instruction_checks_json, s.instruction_detail_json, eo.process_type, eo.item_id
        FROM experiment_samples s
        JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
        JOIN development_projects p ON p.project_id = eo.project_id
        JOIN items i ON i.item_id = eo.item_id
        LEFT JOIN experiment_instructions ei ON ei.experiment_instruction_id = s.experiment_instruction_id
        LEFT JOIN mb_requests mr ON mr.mb_request_id = s.mb_request_id
        LEFT JOIN molds m ON m.mold_id = s.used_mold_id
        LEFT JOIN print_films f ON f.print_film_id = s.used_film_id
        ORDER BY s.sample_id DESC
        """
    )


@st.cache_data(show_spinner=False)
def get_sample_workflow() -> pd.DataFrame:
    return query_df(
        """
        SELECT s.sample_id, s.experiment_instruction_id, ei.instruction_code, s.sample_code, eo.order_code, eo.product_id, p.project_code, i.item_name, eo.process_type, eo.item_id,
               s.status, eo.requirement_date, ei.instruction_date, s.experiment_date, eo.milestone_name, eo.target_due_date,
               eo.base_drawing_revision, eo.drawing_receipt_status, eo.mold_pre_update,
               s.customer_delivery_date, s.customer_result_date, s.customer_result, s.customer_result_notes,
               opr.mold_ready, opr.material_ready, opr.film_ready, opr.drawing_ready,
               opr.condition_input, opr.first_measurement, opr.op_detail_json, opr.first_action, opr.checked_by, opr.checked_at,
               qr.quality_review_date, qr.second_measurement, qr.after_24h_measurement, qr.post_process_review,
               qr.assembly_review, qr.quality_comment,
               fr.final_review_date, fr.final_comment, fr.final_action, fr.approval_status
        FROM experiment_samples s
        JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
        JOIN development_projects p ON p.project_id = eo.project_id
        JOIN items i ON i.item_id = eo.item_id
        LEFT JOIN experiment_instructions ei ON ei.experiment_instruction_id = s.experiment_instruction_id
        LEFT JOIN sample_op_reviews opr ON opr.sample_id = s.sample_id
        LEFT JOIN sample_quality_reviews qr ON qr.sample_id = s.sample_id
        LEFT JOIN sample_final_reviews fr ON fr.sample_id = s.sample_id
        ORDER BY s.sample_id DESC
        """
    )


def reset_cache() -> None:
    print("[CACHE] reset_cache enter")
    get_projects.clear()
    get_products.clear()
    get_product_drawings.clear()
    get_mold_drawings.clear()
    get_molds.clear()
    get_mold_dispatch_orders.clear()
    get_document_revision_orders.clear()
    get_postprocess_item_moves.clear()
    get_print_films.clear()
    get_items.clear()
    get_raw_materials.clear()
    get_sub_materials.clear()
    get_mb_materials.clear()
    get_mb_requests.clear()
    get_mb_receipts.clear()
    get_users.clear()
    get_roles.clear()
    get_role_menu_permissions.clear()
    get_item_bom.clear()
    get_experiment_orders.clear()
    get_experiment_samples.clear()
    get_sample_workflow.clear()
    get_sample_inventory.clear()
    print("[CACHE] reset_cache exit")


def project_options() -> list[tuple[str, int]]:
    df = get_projects()
    if df.empty:
        return []
    return [(f"{row['project_code']} | {row['product_name']}", int(row["project_id"])) for _, row in df.iterrows()]


def get_project_by_code(project_code: str) -> pd.Series | None:
    df = get_projects()
    if df.empty or not project_code:
        return None
    matched = df[df["project_code"] == project_code]
    if matched.empty:
        return None
    return matched.iloc[0]


def product_options() -> list[tuple[str, int]]:
    df = get_products()
    if df.empty:
        return []
    return [(f"{row['project_code']} | {row['product_code']} | {row['product_name']}", int(row["product_id"])) for _, row in df.iterrows()]


def get_item_row(item_id: int | None) -> pd.Series | None:
    if not item_id:
        return None
    df = get_items()
    if df.empty:
        return None
    matched = df[df["item_id"] == item_id]
    if matched.empty:
        return None
    return matched.iloc[0]


def infer_process_type_from_item(item_row: pd.Series | None) -> str:
    return infer_process_type(item_row, EXPERIMENT_PROCESS_OPTIONS)


def product_drawing_options() -> list[tuple[str, int]]:
    df = get_product_drawings()
    if df.empty:
        return []
    latest_df = latest_rows_by_code(df, "drawing_no", "product_drawing_id", "is_current")
    return [(f"{row['project_code']} | {row['drawing_no']} | {row['revision_no']}", int(row["product_drawing_id"])) for _, row in latest_df.iterrows()]


def mold_drawing_options() -> list[tuple[str, int]]:
    df = get_mold_drawings()
    if df.empty:
        return []
    return [(f"{row['project_code']} | {row['mold_drawing_no']} | {row['revision_no']}", int(row["mold_drawing_id"])) for _, row in df.iterrows()]


def mold_options() -> list[tuple[str, int]]:
    df = get_molds()
    if df.empty:
        return []
    return [(f"{row['project_code']} | {row['mold_code']} | {row['mold_name']}", int(row["mold_id"])) for _, row in df.iterrows()]


def item_options() -> list[tuple[str, int]]:
    df = get_items()
    if df.empty:
        return []
    return [(f"{row['project_code'] or '-'} | {row['item_code']} | {row['item_name']}", int(row["item_id"])) for _, row in df.iterrows()]


def item_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_items()
    df = df[df["project_code"] == project_code]
    return [(f"{row['item_code']} | {row['item_name']}", int(row["item_id"])) for _, row in df.iterrows()]


def project_item_tree_options(project_code: str, product_id: int | None = None) -> list[tuple[str, int]]:
    items_df = get_items()
    bom_df = get_item_bom()
    if items_df.empty or not project_code:
        return []
    products_df = get_products()
    selected_product = (
        products_df[
            (pd.to_numeric(products_df["product_id"], errors="coerce") == int(product_id))
            & (products_df["project_code"].astype(str) == str(project_code))
        ]
        if product_id and not products_df.empty
        else products_df.iloc[0:0]
    )
    root_item_id = None
    if not selected_product.empty:
        root_value = selected_product.iloc[0].get("root_item_id")
        if pd.isna(root_value):
            root_value = selected_product.iloc[0].get("linked_item_id")
        if pd.notna(root_value):
            root_item_id = int(root_value)

    # 기존 상품 중 루트 공정품이 아직 지정되지 않은 데이터는 종전 product_id
    # 연결을 사용해 표시하고, 루트가 지정된 상품은 BOM만을 구성 기준으로 삼습니다.
    if root_item_id is None:
        legacy_items = items_df[items_df["project_code"] == project_code].copy()
        if product_id:
            legacy_items = legacy_items[
                pd.to_numeric(legacy_items["product_id"], errors="coerce") == int(product_id)
            ].copy()
        return [
            (f"{row['item_code']} | {row['item_name']} | {row['process_type'] or '-'}", int(row["item_id"]))
            for _, row in legacy_items.sort_values(["item_code", "item_name"]).iterrows()
        ]

    project_items = items_df.copy()
    item_map = {
        int(row["item_id"]): {
            "item_code": row["item_code"],
            "item_name": row["item_name"],
            "process_type": row["process_type"] or "-",
        }
        for _, row in project_items.iterrows()
    }
    children_map: dict[int, list[int]] = {}
    if not bom_df.empty:
        item_ids = set(item_map.keys())
        for _, row in bom_df.iterrows():
            parent_id = int(row["parent_item_id"])
            child_id = int(row["child_item_id"])
            if parent_id in item_ids and child_id in item_ids:
                children_map.setdefault(parent_id, []).append(child_id)

    def sort_ids(ids: list[int]) -> list[int]:
        return sorted(ids, key=lambda item_id: (item_map[item_id]["item_code"], item_map[item_id]["item_name"]))

    ordered: list[tuple[str, int]] = []
    visited: set[int] = set()

    def walk(item_id: int, depth: int) -> None:
        if item_id in visited:
            return
        visited.add(item_id)
        info = item_map[item_id]
        indent = "   " * depth
        label = f"{indent}{info['item_code']} | {info['item_name']} | {info['process_type']}"
        ordered.append((label, item_id))
        for child_id in sort_ids(children_map.get(item_id, [])):
            walk(child_id, depth + 1)

    if root_item_id in item_map:
        walk(root_item_id, 0)
    return ordered


def mold_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_molds()
    df = df[df["project_code"] == project_code]
    return [(f"{row['mold_code']} | {row['mold_name']}", int(row["mold_id"])) for _, row in df.iterrows()]


def raw_material_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_raw_materials()
    return [(f"{row['material_code']} | {row['material_name']}", int(row["raw_material_id"])) for _, row in df.iterrows()]


def mb_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_mb_materials()
    return [(f"{row['mb_code']} | {row['mb_name']}", int(row["mb_material_id"])) for _, row in df.iterrows()]


def mb_request_options_for_item(project_code: str, item_id: int) -> list[tuple[str, int]]:
    df = get_mb_requests()
    if df.empty:
        return []
    filtered = df[(df["project_code"] == project_code) & (df["item_id"] == item_id) & (df["purchase_requested"] == 1)]
    return [
        (f"{row['request_code']} | {row['color_nuance']} | {row['supplier_name'] or '-'} | {row['status']}", int(row["mb_request_id"]))
        for _, row in filtered.iterrows()
    ]


def order_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_experiment_orders()
    df = df[df["project_code"] == project_code]
    return [(f"{row['order_code']} | {row['item_name']}", int(row["experiment_order_id"])) for _, row in df.iterrows()]


def film_options() -> list[tuple[str, int]]:
    df = get_print_films()
    if df.empty:
        return []
    latest_df = latest_rows_by_code(df, "film_code", "print_film_id", "is_current")
    return [(f"{row['project_code']} | {row['artwork_type']} | {row['film_code']} | {row['film_name']} | {row['revision_no']}", int(row["print_film_id"])) for _, row in latest_df.iterrows()]


def film_options_for_project(project_code: str) -> list[tuple[str, int]]:
    df = get_print_films()
    df = df[df["project_code"] == project_code]
    latest_df = latest_rows_by_code(df, "film_code", "print_film_id", "is_current")
    return [(f"{row['artwork_type']} | {row['film_code']} | {row['film_name']} | {row['revision_no']}", int(row["print_film_id"])) for _, row in latest_df.iterrows()]


def order_options() -> list[tuple[str, int]]:
    df = get_experiment_orders()
    if df.empty:
        return []
    return [(f"{row['order_code']} | {row['item_name']}", int(row["experiment_order_id"])) for _, row in df.iterrows()]


def sample_options() -> list[tuple[str, int]]:
    df = get_experiment_samples()
    if df.empty:
        return []
    return [(f"{row['sample_code']} | {row['item_name']}", int(row["sample_id"])) for _, row in df.iterrows()]
