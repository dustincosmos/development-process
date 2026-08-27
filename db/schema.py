from __future__ import annotations

from datetime import datetime

from db.runtime import (
    add_column_if_missing,
    create_daily_backup_if_needed,
    get_connection,
    hash_password,
    rebuild_experiment_samples_table_if_needed,
    rebuild_print_films_table_if_needed,
    rebuild_sample_review_tables_if_needed,
)
from domain.constants import ROLE_LABELS


EXPECTED_DEVELOPMENT_PROJECT_COLUMNS: dict[str, str] = {
    "project_code": "TEXT",
    "product_code": "TEXT",
    "customer_name": "TEXT",
    "product_name": "TEXT",
    "development_type": "TEXT",
    "launch_date": "TEXT",
    "packaging_date": "TEXT",
    "production_plan_date": "TEXT",
    "new_product_test_due_date": "TEXT",
    "standard_due_date": "TEXT",
    "t0_date": "TEXT",
    "t1_date": "TEXT",
    "sales_owner": "TEXT",
    "developer_owner": "TEXT",
    "mold_vendor_name": "TEXT",
    "supervisor_name": "TEXT",
    "status": "TEXT NOT NULL DEFAULT '초기등록'",
    "notes": "TEXT",
    "created_by": "TEXT",
    "created_at": "TEXT",
}


def ensure_development_projects_schema(conn) -> None:
    for column_name, definition in EXPECTED_DEVELOPMENT_PROJECT_COLUMNS.items():
        add_column_if_missing(conn, "development_projects", column_name, definition)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS roles (
                role_code TEXT PRIMARY KEY,
                role_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                login_id TEXT NOT NULL UNIQUE,
                user_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role_code TEXT NOT NULL,
                department TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(role_code) REFERENCES roles(role_code)
            );

            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, role_code),
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(role_code) REFERENCES roles(role_code)
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS role_menu_permissions (
                role_code TEXT NOT NULL,
                menu_group TEXT NOT NULL,
                menu_name TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                PRIMARY KEY (role_code, menu_group, menu_name),
                FOREIGN KEY(role_code) REFERENCES roles(role_code) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS development_projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_code TEXT NOT NULL UNIQUE,
                product_code TEXT,
                customer_name TEXT NOT NULL,
                product_name TEXT NOT NULL,
                development_type TEXT,
                launch_date TEXT,
                packaging_date TEXT,
                production_plan_date TEXT,
                new_product_test_due_date TEXT,
                standard_due_date TEXT,
                t0_date TEXT,
                t1_date TEXT,
                sales_owner TEXT,
                developer_owner TEXT,
                mold_vendor_name TEXT,
                supervisor_name TEXT,
                status TEXT NOT NULL DEFAULT '초기등록',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS product_drawings (
                product_drawing_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                drawing_no TEXT NOT NULL,
                drawing_name TEXT NOT NULL,
                revision_no TEXT NOT NULL,
                file_note TEXT,
                file_path TEXT,
                is_current INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS mold_drawings (
                mold_drawing_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                product_drawing_id INTEGER,
                mold_drawing_no TEXT NOT NULL,
                revision_no TEXT NOT NULL,
                cavity_layout TEXT,
                design_priority TEXT,
                file_path TEXT,
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(product_drawing_id) REFERENCES product_drawings(product_drawing_id)
            );

            CREATE TABLE IF NOT EXISTS molds (
                mold_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                mold_drawing_id INTEGER,
                mold_code TEXT NOT NULL UNIQUE,
                mold_name TEXT NOT NULL,
                cavity INTEGER NOT NULL DEFAULT 1,
                vendor_name TEXT,
                status TEXT NOT NULL DEFAULT '개발중',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(mold_drawing_id) REFERENCES mold_drawings(mold_drawing_id)
            );

            CREATE TABLE IF NOT EXISTS mold_dispatch_orders (
                mold_dispatch_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_order_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                mold_id INTEGER,
                dispatch_code TEXT NOT NULL UNIQUE,
                dispatch_reason TEXT,
                sample_request_date TEXT,
                dispatch_date TEXT,
                receipt_date TEXT,
                modification_note TEXT,
                status TEXT NOT NULL DEFAULT '출고지시',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_order_id) REFERENCES experiment_orders(experiment_order_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id),
                FOREIGN KEY(mold_id) REFERENCES molds(mold_id)
            );

            CREATE TABLE IF NOT EXISTS document_revision_orders (
                document_revision_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_order_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                document_type TEXT NOT NULL,
                base_document_id INTEGER,
                request_code TEXT NOT NULL UNIQUE,
                request_reason TEXT,
                expected_receipt_date TEXT,
                receipt_date TEXT,
                status TEXT NOT NULL DEFAULT '수정요청',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_order_id) REFERENCES experiment_orders(experiment_order_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS postprocess_item_moves (
                postprocess_move_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id INTEGER,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                actual_item_id INTEGER,
                wms_kind TEXT,
                vendor_name TEXT,
                child_dispatch_note TEXT,
                dispatch_date TEXT,
                expected_receipt_date TEXT,
                receipt_date TEXT,
                status TEXT NOT NULL DEFAULT '출고지시',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id),
                FOREIGN KEY(actual_item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS sample_inventory (
                sample_id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                qty_on_hand REAL NOT NULL DEFAULT 0,
                qty_reserved REAL NOT NULL DEFAULT 0,
                current_location TEXT NOT NULL DEFAULT '샘플창고',
                partner_name TEXT NOT NULL DEFAULT '내부',
                status TEXT NOT NULL DEFAULT '가용',
                updated_by TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS sample_inventory_adjustments (
                adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                qty_delta REAL NOT NULL,
                reason TEXT NOT NULL,
                note TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS print_films (
                print_film_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                film_code TEXT NOT NULL UNIQUE,
                film_name TEXT NOT NULL,
                artwork_type TEXT NOT NULL DEFAULT '인쇄',
                revision_no TEXT NOT NULL,
                related_item_name TEXT,
                status TEXT NOT NULL DEFAULT '개발중',
                file_path TEXT,
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                product_id INTEGER,
                item_code TEXT NOT NULL UNIQUE,
                item_name TEXT NOT NULL,
                item_class TEXT NOT NULL,
                item_type TEXT NOT NULL,
                process_type TEXT,
                product_drawing_id INTEGER,
                base_print_film_id INTEGER,
                primary_mold_id INTEGER,
                base_revision_no TEXT,
                base_material_label TEXT,
                base_color_label TEXT,
                mb_note TEXT,
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(product_id) REFERENCES products(product_id),
                FOREIGN KEY(product_drawing_id) REFERENCES product_drawings(product_drawing_id),
                FOREIGN KEY(base_print_film_id) REFERENCES print_films(print_film_id),
                FOREIGN KEY(primary_mold_id) REFERENCES molds(mold_id)
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                product_code TEXT NOT NULL UNIQUE,
                product_name TEXT NOT NULL,
                root_item_id INTEGER,
                linked_item_id INTEGER,
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(root_item_id) REFERENCES items(item_id),
                FOREIGN KEY(linked_item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS raw_materials (
                raw_material_id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_code TEXT NOT NULL UNIQUE,
                material_name TEXT NOT NULL,
                material_type TEXT NOT NULL DEFAULT '원료',
                supplier_name TEXT,
                status TEXT NOT NULL DEFAULT '사용중',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sub_materials (
                sub_material_id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_code TEXT NOT NULL UNIQUE,
                material_name TEXT NOT NULL,
                material_type TEXT NOT NULL DEFAULT '기타',
                supplier_name TEXT,
                backing_diameter TEXT,
                backing_thickness TEXT,
                backing_material_type TEXT,
                label_film_id INTEGER,
                status TEXT NOT NULL DEFAULT '사용중',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(label_film_id) REFERENCES print_films(print_film_id)
            );

            CREATE TABLE IF NOT EXISTS mb_materials (
                mb_material_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mb_code TEXT NOT NULL UNIQUE,
                mb_name TEXT NOT NULL,
                supplier_name TEXT,
                status TEXT NOT NULL DEFAULT '개발중',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mb_requests (
                mb_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_order_id INTEGER NOT NULL UNIQUE,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                request_code TEXT NOT NULL UNIQUE,
                color_nuance TEXT NOT NULL,
                color_sample_exists INTEGER NOT NULL DEFAULT 0,
                supplier_name TEXT,
                consultation_note TEXT,
                sample_sent INTEGER NOT NULL DEFAULT 0,
                sample_received INTEGER NOT NULL DEFAULT 0,
                expected_receipt_date TEXT,
                purchase_requested INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '의뢰등록',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_order_id) REFERENCES experiment_orders(experiment_order_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS mb_receipts (
                mb_receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mb_request_id INTEGER NOT NULL,
                receipt_date TEXT,
                receipt_qty REAL,
                lot_no TEXT,
                receipt_note TEXT,
                status TEXT NOT NULL DEFAULT '입고완료',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(mb_request_id) REFERENCES mb_requests(mb_request_id)
            );

            CREATE TABLE IF NOT EXISTS item_bom (
                bom_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                parent_item_id INTEGER NOT NULL,
                child_item_id INTEGER NOT NULL,
                qty REAL NOT NULL DEFAULT 1,
                qty_unit TEXT NOT NULL DEFAULT 'ea',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(parent_item_id, child_item_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(parent_item_id) REFERENCES items(item_id),
                FOREIGN KEY(child_item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS experiment_orders (
                experiment_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT NOT NULL UNIQUE,
                meta_requirement_id INTEGER,
                project_id INTEGER NOT NULL,
                product_id INTEGER,
                item_id INTEGER NOT NULL,
                process_type TEXT NOT NULL,
                requirement_date TEXT,
                milestone_name TEXT,
                base_drawing_revision TEXT,
                drawing_receipt_status TEXT,
                mold_pre_update INTEGER NOT NULL DEFAULT 0,
                target_due_date TEXT,
                milestone_due_date TEXT,
                required_sample_qty INTEGER NOT NULL DEFAULT 1,
                experiment_goal TEXT,
                success_criteria TEXT,
                request_notes TEXT,
                requirement_checks_json TEXT,
                requirement_detail_json TEXT,
                requested_by TEXT,
                status TEXT NOT NULL DEFAULT '지시등록',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(meta_requirement_id) REFERENCES meta_requirements(meta_requirement_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(product_id) REFERENCES products(product_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS experiment_instructions (
                experiment_instruction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                instruction_code TEXT NOT NULL UNIQUE,
                experiment_order_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                process_type TEXT NOT NULL,
                instruction_date TEXT,
                required_sample_qty INTEGER NOT NULL DEFAULT 1,
                requested_finish_date TEXT,
                machine_no TEXT,
                machine_ton TEXT,
                instruction_detail_json TEXT,
                requirement_completed INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '진행중',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_order_id) REFERENCES experiment_orders(experiment_order_id),
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS meta_requirements (
                meta_requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                meta_code TEXT NOT NULL UNIQUE,
                project_id INTEGER NOT NULL,
                product_id INTEGER,
                root_item_id INTEGER,
                tree_mode TEXT NOT NULL DEFAULT '기본',
                title TEXT,
                status TEXT NOT NULL DEFAULT '요구등록',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(product_id) REFERENCES products(product_id),
                FOREIGN KEY(root_item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS meta_requirement_lines (
                meta_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
                meta_requirement_id INTEGER NOT NULL,
                item_id INTEGER,
                parent_meta_line_id INTEGER,
                parent_item_id INTEGER,
                line_order INTEGER NOT NULL DEFAULT 0,
                level_no INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL DEFAULT 'part',
                source_type TEXT NOT NULL DEFAULT '기본',
                is_virtual_root INTEGER NOT NULL DEFAULT 0,
                display_name TEXT,
                notes TEXT,
                FOREIGN KEY(meta_requirement_id) REFERENCES meta_requirements(meta_requirement_id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES items(item_id),
                FOREIGN KEY(parent_meta_line_id) REFERENCES meta_requirement_lines(meta_line_id)
            );

            CREATE TABLE IF NOT EXISTS experiment_samples (
                sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_order_id INTEGER NOT NULL,
                sample_code TEXT NOT NULL UNIQUE,
                sample_seq INTEGER NOT NULL,
                experiment_date TEXT,
                sample_name TEXT,
                variation_note TEXT,
                mb_request_id INTEGER,
                used_mold_id INTEGER,
                used_film_id INTEGER,
                customer_delivery_date TEXT,
                customer_result_date TEXT,
                customer_result TEXT,
                customer_result_notes TEXT,
                instruction_checks_json TEXT,
                instruction_detail_json TEXT,
                status TEXT NOT NULL DEFAULT '샘플생성',
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_order_id) REFERENCES experiment_orders(experiment_order_id),
                FOREIGN KEY(mb_request_id) REFERENCES mb_requests(mb_request_id),
                FOREIGN KEY(used_mold_id) REFERENCES molds(mold_id),
                FOREIGN KEY(used_film_id) REFERENCES print_films(print_film_id)
            );

            CREATE TABLE IF NOT EXISTS sample_op_reviews (
                sample_id INTEGER PRIMARY KEY,
                mold_ready INTEGER NOT NULL DEFAULT 0,
                material_ready INTEGER NOT NULL DEFAULT 0,
                film_ready INTEGER NOT NULL DEFAULT 0,
                drawing_ready INTEGER NOT NULL DEFAULT 0,
                condition_input TEXT,
                first_measurement TEXT,
                op_detail_json TEXT,
                first_action TEXT,
                checked_by TEXT,
                checked_at TEXT,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id)
            );

            CREATE TABLE IF NOT EXISTS sample_quality_reviews (
                sample_id INTEGER PRIMARY KEY,
                quality_review_date TEXT,
                second_measurement TEXT,
                after_24h_measurement TEXT,
                post_process_review TEXT,
                assembly_review TEXT,
                quality_comment TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id)
            );

            CREATE TABLE IF NOT EXISTS sample_final_reviews (
                sample_id INTEGER PRIMARY KEY,
                final_review_date TEXT,
                final_comment TEXT,
                final_action TEXT,
                approval_status TEXT NOT NULL DEFAULT '검토중',
                reviewed_by TEXT,
                reviewed_at TEXT,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id)
            );

            CREATE TABLE IF NOT EXISTS cost_simulation_headers (
                simulation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                simulation_name TEXT NOT NULL,
                notes TEXT,
                total_cost REAL NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES development_projects(project_id),
                FOREIGN KEY(item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS cost_simulation_lines (
                simulation_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                parent_item_id INTEGER,
                level_no INTEGER NOT NULL DEFAULT 0,
                process_type TEXT,
                qty REAL NOT NULL DEFAULT 1,
                qty_unit TEXT NOT NULL DEFAULT 'ea',
                material_cost REAL NOT NULL DEFAULT 0,
                process_cost REAL NOT NULL DEFAULT 0,
                defect_rate_pct REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                notes TEXT,
                FOREIGN KEY(simulation_id) REFERENCES cost_simulation_headers(simulation_id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES items(item_id),
                FOREIGN KEY(parent_item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS resource_rates (
                resource_code TEXT PRIMARY KEY,
                resource_name TEXT NOT NULL,
                daily_rate REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS simulation_headers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_name TEXT NOT NULL,
                product_code TEXT NOT NULL,
                product_name TEXT NOT NULL,
                customer TEXT,
                daily_hours REAL NOT NULL DEFAULT 22,
                total_cost REAL NOT NULL DEFAULT 0,
                input_state_json TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS simulation_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_id INTEGER NOT NULL,
                route_id INTEGER,
                seq INTEGER NOT NULL,
                process_type TEXT NOT NULL,
                process_name TEXT NOT NULL,
                output_item_id TEXT NOT NULL,
                output_item_name TEXT NOT NULL,
                material_cost REAL NOT NULL DEFAULT 0,
                process_cost REAL NOT NULL DEFAULT 0,
                packaging_cost REAL NOT NULL DEFAULT 0,
                moving_cost REAL NOT NULL DEFAULT 0,
                own_cost REAL NOT NULL DEFAULT 0,
                cumulative_cost REAL NOT NULL DEFAULT 0,
                formula_text TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                item_id TEXT,
                item_name TEXT,
                item_kind TEXT,
                FOREIGN KEY(simulation_id) REFERENCES simulation_headers(id) ON DELETE CASCADE
            );
            """
        )
        rebuild_print_films_table_if_needed(conn)
        rebuild_experiment_samples_table_if_needed(conn)
        rebuild_sample_review_tables_if_needed(conn)
        role_menu_pk_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(role_menu_permissions)").fetchall()
            if int(row["pk"])
        }
        if role_menu_pk_columns and role_menu_pk_columns != {"role_code", "menu_group", "menu_name"}:
            conn.executescript(
                """
                ALTER TABLE role_menu_permissions RENAME TO role_menu_permissions_old;

                CREATE TABLE role_menu_permissions (
                    role_code TEXT NOT NULL,
                    menu_group TEXT NOT NULL,
                    menu_name TEXT NOT NULL,
                    is_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (role_code, menu_group, menu_name),
                    FOREIGN KEY(role_code) REFERENCES roles(role_code) ON DELETE CASCADE
                );

                INSERT OR REPLACE INTO role_menu_permissions (
                    role_code, menu_group, menu_name, is_enabled, created_at
                )
                SELECT role_code, menu_group, menu_name, is_enabled, created_at
                FROM role_menu_permissions_old;

                DROP TABLE role_menu_permissions_old;
                """
            )
        add_column_if_missing(conn, "roles", "is_active", "INTEGER NOT NULL DEFAULT 1")
        ensure_development_projects_schema(conn)
        add_column_if_missing(conn, "product_drawings", "file_path", "TEXT")
        add_column_if_missing(conn, "mold_drawings", "file_path", "TEXT")
        add_column_if_missing(conn, "print_films", "file_path", "TEXT")
        add_column_if_missing(conn, "print_films", "is_current", "INTEGER NOT NULL DEFAULT 1")
        add_column_if_missing(conn, "print_films", "artwork_type", "TEXT NOT NULL DEFAULT '인쇄'")
        add_column_if_missing(conn, "experiment_orders", "requirement_date", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "product_id", "INTEGER")
        add_column_if_missing(conn, "experiment_instructions", "instruction_date", "TEXT")
        add_column_if_missing(conn, "experiment_samples", "experiment_date", "TEXT")
        add_column_if_missing(conn, "sample_quality_reviews", "quality_review_date", "TEXT")
        add_column_if_missing(conn, "sample_final_reviews", "final_review_date", "TEXT")
        add_column_if_missing(conn, "items", "product_id", "INTEGER")
        add_column_if_missing(conn, "items", "base_revision_no", "TEXT")
        add_column_if_missing(conn, "items", "base_print_film_id", "INTEGER")
        add_column_if_missing(conn, "items", "base_material_label", "TEXT")
        add_column_if_missing(conn, "items", "base_color_label", "TEXT")
        add_column_if_missing(conn, "products", "linked_item_id", "INTEGER")
        add_column_if_missing(conn, "experiment_orders", "requirement_checks_json", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "requirement_detail_json", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "milestone_name", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "base_drawing_revision", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "drawing_receipt_status", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "mold_pre_update", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "experiment_orders", "mold_dispatch_required", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "experiment_orders", "milestone_due_date", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "success_criteria", "TEXT")
        add_column_if_missing(conn, "experiment_orders", "meta_requirement_id", "INTEGER")
        add_column_if_missing(conn, "experiment_orders", "meta_line_id", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_experiment_order_id", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_required_sample_qty", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_injection_instruction_id", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_process_instruction_id", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_assembly_instruction_id", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_print_instruction_id", "INTEGER")
        add_column_if_missing(conn, "meta_requirement_lines", "linked_postprocess_instruction_id", "INTEGER")
        add_column_if_missing(conn, "experiment_samples", "experiment_instruction_id", "INTEGER")
        add_column_if_missing(conn, "experiment_samples", "mb_request_id", "INTEGER")
        add_column_if_missing(conn, "experiment_samples", "instruction_checks_json", "TEXT")
        add_column_if_missing(conn, "experiment_samples", "instruction_detail_json", "TEXT")
        add_column_if_missing(conn, "experiment_samples", "customer_delivery_date", "TEXT")
        add_column_if_missing(conn, "experiment_samples", "customer_result_date", "TEXT")
        add_column_if_missing(conn, "experiment_samples", "customer_result", "TEXT")
        add_column_if_missing(conn, "experiment_samples", "customer_result_notes", "TEXT")
        add_column_if_missing(conn, "sample_op_reviews", "op_detail_json", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "move_code", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "source_type", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "source_order_id", "INTEGER")
        add_column_if_missing(conn, "postprocess_item_moves", "source_instruction_id", "INTEGER")
        add_column_if_missing(conn, "postprocess_item_moves", "product_id", "INTEGER")
        add_column_if_missing(conn, "postprocess_item_moves", "process_type", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "actual_item_id", "INTEGER")
        add_column_if_missing(conn, "postprocess_item_moves", "wms_kind", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "execution_mode", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "partner_name", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "from_location", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "to_location", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "requested_qty", "REAL NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "postprocess_item_moves", "dispatch_qty", "REAL")
        add_column_if_missing(conn, "postprocess_item_moves", "receipt_qty", "REAL")
        add_column_if_missing(conn, "postprocess_item_moves", "receipt_note", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "inventory_status", "TEXT")
        add_column_if_missing(conn, "postprocess_item_moves", "unit_cost", "REAL")
        add_column_if_missing(conn, "postprocess_item_moves", "uph", "REAL")
        add_column_if_missing(conn, "postprocess_item_moves", "defect_rate", "REAL")
        add_column_if_missing(conn, "postprocess_item_moves", "moq", "REAL")
        add_column_if_missing(conn, "sub_materials", "backing_diameter", "TEXT")
        add_column_if_missing(conn, "sub_materials", "backing_thickness", "TEXT")
        add_column_if_missing(conn, "sub_materials", "backing_material_type", "TEXT")
        add_column_if_missing(conn, "sub_materials", "label_film_id", "INTEGER")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_postprocess_item_moves_move_code ON postprocess_item_moves(move_code)")
        conn.execute("UPDATE postprocess_item_moves SET partner_name = COALESCE(partner_name, vendor_name, '내부') WHERE COALESCE(partner_name, '') = ''")
        conn.execute("UPDATE postprocess_item_moves SET actual_item_id = COALESCE(actual_item_id, item_id) WHERE actual_item_id IS NULL")
        conn.execute("UPDATE postprocess_item_moves SET execution_mode = COALESCE(execution_mode, CASE WHEN COALESCE(partner_name, vendor_name, '내부') = '내부' THEN '내부' ELSE '외주' END) WHERE COALESCE(execution_mode, '') = ''")
        conn.execute("UPDATE postprocess_item_moves SET process_type = COALESCE(process_type, '후가공') WHERE COALESCE(process_type, '') = ''")
        conn.execute(
            """
            UPDATE mold_dispatch_orders
            SET sample_request_date = (
                SELECT eo.target_due_date
                FROM experiment_orders eo
                WHERE eo.experiment_order_id = mold_dispatch_orders.experiment_order_id
            )
            WHERE COALESCE(sample_request_date, '') = ''
            """
        )
        conn.execute(
            """
            UPDATE postprocess_item_moves
            SET wms_kind = COALESCE(
                wms_kind,
                CASE
                    WHEN source_type = '고객요구' THEN '고객출고지시'
                    WHEN source_type = '전공정요구' THEN '전공정품출고지시'
                    WHEN source_instruction_id IS NOT NULL AND status IN ('입고예정', '입고완료') THEN '입고예정'
                    ELSE '공정품출고지시'
                END
            )
            WHERE COALESCE(wms_kind, '') = ''
            """
        )
        conn.execute("UPDATE postprocess_item_moves SET inventory_status = COALESCE(inventory_status, CASE WHEN status = '입고완료' THEN '보관' WHEN status = '출고완료' THEN '출고중' ELSE '예약' END) WHERE COALESCE(inventory_status, '') = ''")
        conn.execute("UPDATE postprocess_item_moves SET move_code = COALESCE(move_code, 'WMS-' || printf('%06d', postprocess_move_id)) WHERE COALESCE(move_code, '') = ''")
        role_count = int(conn.execute("SELECT COUNT(*) AS cnt FROM roles").fetchone()["cnt"])
        if role_count == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO roles (role_code, role_name) VALUES (?, ?)",
                list(ROLE_LABELS.items()),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO users (login_id, user_name, password_hash, role_code, department, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            ("admin", "관리자", hash_password("admin1234"), "admin", "관리", datetime.now().isoformat(timespec="seconds")),
        )
        existing_products = conn.execute("SELECT COUNT(*) AS cnt FROM products").fetchone()["cnt"]
        if existing_products == 0:
            project_rows = conn.execute(
                """
                SELECT project_id, product_code, product_name
                FROM development_projects
                WHERE COALESCE(product_code, '') <> ''
                ORDER BY project_id
                """
            ).fetchall()
            for row in project_rows:
                project_id = int(row["project_id"])
                root_row = conn.execute(
                    """
                    SELECT i.item_id
                    FROM items i
                    LEFT JOIN item_bom b ON b.child_item_id = i.item_id
                    WHERE i.project_id = ? AND b.child_item_id IS NULL
                    ORDER BY i.item_id
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
                root_item_id = int(root_row["item_id"]) if root_row is not None else None
                cur = conn.execute(
                    """
                    INSERT INTO products (project_id, product_code, product_name, root_item_id, linked_item_id, notes, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        row["product_code"],
                        row["product_name"],
                        root_item_id,
                        root_item_id,
                        "",
                        "system",
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                product_id = int(cur.lastrowid)
                conn.execute(
                    "UPDATE items SET product_id = ? WHERE project_id = ? AND product_id IS NULL",
                    (product_id, project_id),
                )
        conn.execute("UPDATE products SET linked_item_id = root_item_id WHERE linked_item_id IS NULL")
        conn.execute(
            """
            UPDATE experiment_orders
            SET product_id = COALESCE(
                (
                    SELECT mr.product_id
                    FROM meta_requirements mr
                    WHERE mr.meta_requirement_id = experiment_orders.meta_requirement_id
                ),
                CASE
                    WHEN json_valid(COALESCE(requirement_detail_json, ''))
                    THEN CAST(json_extract(requirement_detail_json, '$._meta_product_id') AS INTEGER)
                    ELSE NULL
                END,
                (
                    SELECT i.product_id
                    FROM items i
                    WHERE i.item_id = experiment_orders.item_id
                )
            )
            WHERE product_id IS NULL
            """
        )
        conn.execute(
            """
            UPDATE experiment_orders
            SET meta_line_id = (
                SELECT ml.meta_line_id
                FROM meta_requirement_lines ml
                WHERE ml.meta_requirement_id = experiment_orders.meta_requirement_id
                  AND ml.item_id = experiment_orders.item_id
                ORDER BY ml.line_order, ml.meta_line_id
                LIMIT 1
            )
            WHERE meta_requirement_id IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM meta_requirement_lines ml
                  WHERE ml.meta_requirement_id = experiment_orders.meta_requirement_id
                    AND ml.item_id = experiment_orders.item_id
              )
              AND (
                  meta_line_id IS NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM meta_requirement_lines current_ml
                      WHERE current_ml.meta_line_id = experiment_orders.meta_line_id
                        AND current_ml.meta_requirement_id = experiment_orders.meta_requirement_id
                        AND current_ml.item_id = experiment_orders.item_id
                  )
              )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO user_roles (user_id, role_code, created_at)
            SELECT user_id, role_code, created_at
            FROM users
            WHERE COALESCE(role_code, '') <> ''
            """
        )
        conn.commit()
    create_daily_backup_if_needed()
