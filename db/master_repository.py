from __future__ import annotations

from datetime import datetime

from db.runtime import execute, get_connection, get_table_columns, resolve_db_path, try_delete
from db.schema import EXPECTED_DEVELOPMENT_PROJECT_COLUMNS
from domain.schemas import (
    BomPayload,
    ItemPayload,
    MaterialPayload,
    PrintFilmPayload,
    ProductPayload,
    ProductDrawingPayload,
    ProjectPayload,
)
from services.reference_data_service import reset_cache


def _validate_development_projects_schema() -> None:
    actual_columns = set(get_table_columns("development_projects"))
    expected_columns = set(EXPECTED_DEVELOPMENT_PROJECT_COLUMNS.keys()) | {"project_id"}
    missing_columns = sorted(expected_columns - actual_columns)
    if missing_columns:
        raise RuntimeError(
            f"development_projects 스키마 누락: {', '.join(missing_columns)} | DB={resolve_db_path()}"
        )


def delete_project(project_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM development_projects WHERE project_id = ?", (project_id,))
    if ok:
        reset_cache()
    return ok, message


def save_project(selected_project_id: int | None, payload: ProjectPayload, current_user_name: str) -> None:
    _validate_development_projects_schema()
    if selected_project_id is None:
        execute(
            """
            INSERT INTO development_projects (
                project_code, customer_name, product_name, development_type, launch_date, packaging_date,
                production_plan_date, new_product_test_due_date, standard_due_date, t0_date, t1_date,
                sales_owner, developer_owner, mold_vendor_name, supervisor_name, status, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["project_code"],
                payload["customer_name"],
                payload["project_name"],
                payload["development_type"],
                payload["launch_date"],
                payload["packaging_date"],
                payload["production_plan_date"],
                payload["new_product_test_due_date"],
                payload["standard_due_date"],
                payload["t0_date"],
                payload["t1_date"],
                payload["sales_owner"],
                payload["developer_owner"],
                payload["mold_vendor_name"],
                payload["supervisor_name"],
                payload["status"],
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
            debug_label="development_projects INSERT",
        )
    else:
        execute(
            """
            UPDATE development_projects
            SET project_code = ?, customer_name = ?, product_name = ?, development_type = ?,
                launch_date = ?, packaging_date = ?, production_plan_date = ?, new_product_test_due_date = ?,
                standard_due_date = ?, t0_date = ?, t1_date = ?, sales_owner = ?, developer_owner = ?, mold_vendor_name = ?, supervisor_name = ?, status = ?, notes = ?
            WHERE project_id = ?
            """,
            (
                payload["project_code"],
                payload["customer_name"],
                payload["project_name"],
                payload["development_type"],
                payload["launch_date"],
                payload["packaging_date"],
                payload["production_plan_date"],
                payload["new_product_test_due_date"],
                payload["standard_due_date"],
                payload["t0_date"],
                payload["t1_date"],
                payload["sales_owner"],
                payload["developer_owner"],
                payload["mold_vendor_name"],
                payload["supervisor_name"],
                payload["status"],
                payload["notes"],
                selected_project_id,
            ),
            debug_label="development_projects UPDATE",
        )
    with get_connection() as conn:
        saved_row = conn.execute(
            """
            SELECT project_id, project_code, customer_name, product_name, development_type, status
            FROM development_projects
            WHERE project_code = ?
            ORDER BY project_id DESC
            LIMIT 1
            """,
            (payload["project_code"],),
        ).fetchone()
    if saved_row is None:
        raise RuntimeError(
            f"프로젝트 저장 후 재조회 실패: project_code={payload['project_code']} | DB={resolve_db_path()}"
        )
    reset_cache()


def delete_product(product_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM products WHERE product_id = ?", (product_id,))
    if ok:
        reset_cache()
    return ok, message


def save_product(selected_product_id: int | None, payload: ProductPayload, current_user_name: str) -> None:
    if selected_product_id is None:
        execute(
            """
            INSERT INTO products (
                project_id, product_code, product_name, root_item_id, linked_item_id, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["project_id"],
                payload["product_code"],
                payload["product_name"],
                payload["linked_item_id"],
                payload["linked_item_id"],
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE products
            SET project_id = ?, product_code = ?, product_name = ?, root_item_id = ?, linked_item_id = ?, notes = ?
            WHERE product_id = ?
            """,
            (
                payload["project_id"],
                payload["product_code"],
                payload["product_name"],
                payload["linked_item_id"],
                payload["linked_item_id"],
                payload["notes"],
                selected_product_id,
            ),
        )
    reset_cache()


def delete_item(item_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM items WHERE item_id = ?", (item_id,))
    if ok:
        reset_cache()
    return ok, message


def save_item(selected_item_id: int | None, payload: ItemPayload, current_user_name: str) -> None:
    if selected_item_id is None:
        execute(
            """
            INSERT INTO items (
                project_id, product_id, item_code, item_name, item_class, item_type, process_type,
                product_drawing_id, base_print_film_id, primary_mold_id, base_revision_no, base_material_label, base_color_label,
                mb_note, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["project_id"],
                payload["product_id"],
                payload["item_code"],
                payload["item_name"],
                payload["item_class"],
                payload["item_type"],
                payload["process_type"],
                payload["product_drawing_id"],
                payload["base_print_film_id"],
                payload["primary_mold_id"],
                payload["base_revision_no"],
                payload["base_material_label"],
                payload["base_color_label"],
                payload["mb_note"],
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE items
            SET project_id = ?, product_id = ?, item_code = ?, item_name = ?, item_class = ?, item_type = ?, process_type = ?,
                product_drawing_id = ?, base_print_film_id = ?, primary_mold_id = ?, base_revision_no = ?, base_material_label = ?, base_color_label = ?,
                mb_note = ?, notes = ?
            WHERE item_id = ?
            """,
            (
                payload["project_id"],
                payload["product_id"],
                payload["item_code"],
                payload["item_name"],
                payload["item_class"],
                payload["item_type"],
                payload["process_type"],
                payload["product_drawing_id"],
                payload["base_print_film_id"],
                payload["primary_mold_id"],
                payload["base_revision_no"],
                payload["base_material_label"],
                payload["base_color_label"],
                payload["mb_note"],
                payload["notes"],
                selected_item_id,
            ),
        )
    reset_cache()


def delete_bom(bom_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM item_bom WHERE bom_id = ?", (bom_id,))
    if ok:
        reset_cache()
    return ok, message


def save_bom(selected_bom_id: int | None, payload: BomPayload, current_user_name: str) -> None:
    parent_item_id = int(payload["parent_item_id"])
    child_item_id = int(payload["child_item_id"])
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT bom_id, parent_item_id, child_item_id FROM item_bom"
        ).fetchall()
    children_by_parent: dict[int, set[int]] = {}
    for row in rows:
        if selected_bom_id is not None and int(row["bom_id"]) == int(selected_bom_id):
            continue
        children_by_parent.setdefault(int(row["parent_item_id"]), set()).add(int(row["child_item_id"]))
    pending = [child_item_id]
    visited: set[int] = set()
    while pending:
        current_id = pending.pop()
        if current_id == parent_item_id:
            raise ValueError("순환하는 BOM 구조는 등록할 수 없습니다.")
        if current_id in visited:
            continue
        visited.add(current_id)
        pending.extend(children_by_parent.get(current_id, set()))
    if selected_bom_id is None:
        execute(
            """
            INSERT INTO item_bom (
                project_id, parent_item_id, child_item_id, qty, qty_unit, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["project_id"],
                payload["parent_item_id"],
                payload["child_item_id"],
                payload["qty"],
                payload["qty_unit"],
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE item_bom
            SET project_id = ?, parent_item_id = ?, child_item_id = ?, qty = ?, qty_unit = ?, notes = ?
            WHERE bom_id = ?
            """,
            (
                payload["project_id"],
                payload["parent_item_id"],
                payload["child_item_id"],
                payload["qty"],
                payload["qty_unit"],
                payload["notes"],
                selected_bom_id,
            ),
        )
    reset_cache()


def delete_raw_material(raw_material_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM raw_materials WHERE raw_material_id = ?", (raw_material_id,))
    if ok:
        reset_cache()
    return ok, message


def save_raw_material(selected_raw_material_id: int | None, payload: MaterialPayload, current_user_name: str) -> None:
    if selected_raw_material_id is None:
        execute(
            """
            INSERT INTO raw_materials (
                material_code, material_name, material_type, supplier_name, status, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["material_code"],
                payload["material_name"],
                payload["material_type"],
                payload["supplier_name"],
                payload["status"],
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE raw_materials
            SET material_code = ?, material_name = ?, material_type = ?, supplier_name = ?, status = ?, notes = ?
            WHERE raw_material_id = ?
            """,
            (
                payload["material_code"],
                payload["material_name"],
                payload["material_type"],
                payload["supplier_name"],
                payload["status"],
                payload["notes"],
                selected_raw_material_id,
            ),
        )
    reset_cache()


def delete_sub_material(sub_material_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM sub_materials WHERE sub_material_id = ?", (sub_material_id,))
    if ok:
        reset_cache()
    return ok, message


def save_sub_material(selected_sub_material_id: int | None, payload: MaterialPayload, current_user_name: str) -> None:
    if selected_sub_material_id is None:
        execute(
            """
            INSERT INTO sub_materials (
                material_code, material_name, material_type, supplier_name,
                backing_diameter, backing_thickness, backing_material_type, label_film_id,
                status, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["material_code"],
                payload["material_name"],
                payload["material_type"],
                payload["supplier_name"],
                payload["backing_diameter"],
                payload["backing_thickness"],
                payload["backing_material_type"],
                payload["label_film_id"],
                payload["status"],
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE sub_materials
            SET material_code = ?, material_name = ?, material_type = ?, supplier_name = ?,
                backing_diameter = ?, backing_thickness = ?, backing_material_type = ?, label_film_id = ?,
                status = ?, notes = ?
            WHERE sub_material_id = ?
            """,
            (
                payload["material_code"],
                payload["material_name"],
                payload["material_type"],
                payload["supplier_name"],
                payload["backing_diameter"],
                payload["backing_thickness"],
                payload["backing_material_type"],
                payload["label_film_id"],
                payload["status"],
                payload["notes"],
                selected_sub_material_id,
            ),
        )
    reset_cache()


def delete_product_drawing(product_drawing_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM product_drawings WHERE product_drawing_id = ?", (product_drawing_id,))
    if ok:
        reset_cache()
    return ok, message


def save_product_drawing(selected_product_drawing_id: int | None, *, create_new_revision: bool, payload: ProductDrawingPayload, current_user_name: str) -> None:
    if payload["is_current"] and payload["drawing_no"]:
        execute(
            "UPDATE product_drawings SET is_current = 0 WHERE project_id = ? AND drawing_no = ?",
            (payload["project_id"], payload["drawing_no"]),
        )
    if selected_product_drawing_id is None or create_new_revision:
        execute(
            """
            INSERT INTO product_drawings (
                project_id, drawing_no, drawing_name, revision_no, file_note, file_path,
                is_current, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["project_id"],
                payload["drawing_no"],
                payload["drawing_name"],
                payload["revision_no"],
                payload["file_note"],
                payload["file_path"],
                1 if payload["is_current"] else 0,
                payload["notes"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE product_drawings
            SET project_id = ?, drawing_no = ?, drawing_name = ?, revision_no = ?, file_note = ?,
                file_path = ?, is_current = ?, notes = ?
            WHERE product_drawing_id = ?
            """,
            (
                payload["project_id"],
                payload["drawing_no"],
                payload["drawing_name"],
                payload["revision_no"],
                payload["file_note"],
                payload["file_path"],
                1 if payload["is_current"] else 0,
                payload["notes"],
                selected_product_drawing_id,
            ),
        )
    reset_cache()


def delete_print_film(print_film_id: int) -> tuple[bool, str]:
    ok, message = try_delete("DELETE FROM print_films WHERE print_film_id = ?", (print_film_id,))
    if ok:
        reset_cache()
    return ok, message


def save_print_film(selected_print_film_id: int | None, *, create_new_revision: bool, payload: PrintFilmPayload, current_user_name: str) -> None:
    if payload["is_current"] and payload["film_code"]:
        execute(
            "UPDATE print_films SET is_current = 0 WHERE project_id = ? AND film_code = ?",
            (payload["project_id"], payload["film_code"]),
        )
    if selected_print_film_id is None or create_new_revision:
        execute(
            """
            INSERT INTO print_films (
                project_id, film_code, film_name, artwork_type, revision_no, related_item_name,
                status, file_path, notes, is_current, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["project_id"],
                payload["film_code"],
                payload["film_name"],
                payload["artwork_type"],
                payload["revision_no"],
                payload["related_item_name"],
                payload["status"],
                payload["file_path"],
                payload["notes"],
                1 if payload["is_current"] else 0,
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE print_films
            SET project_id = ?, film_code = ?, film_name = ?, artwork_type = ?, revision_no = ?, related_item_name = ?,
                status = ?, file_path = ?, notes = ?, is_current = ?
            WHERE print_film_id = ?
            """,
            (
                payload["project_id"],
                payload["film_code"],
                payload["film_name"],
                payload["artwork_type"],
                payload["revision_no"],
                payload["related_item_name"],
                payload["status"],
                payload["file_path"],
                payload["notes"],
                1 if payload["is_current"] else 0,
                selected_print_film_id,
            ),
        )
    reset_cache()
