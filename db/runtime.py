from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from db.paths import DB_BACKUP_DIR, DEV_DB_PATH, UPLOADS_DIR


SQLITE_BUSY_TIMEOUT_MS = 15_000
SQLITE_SYNCHRONOUS_MODE = "NORMAL"
LOGGER = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_connection(db_path: Path = DEV_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA synchronous = {SQLITE_SYNCHRONOUS_MODE}")
    return conn


def resolve_db_path(db_path: Path = DEV_DB_PATH) -> Path:
    return db_path.resolve()


def get_table_columns(table_name: str, db_path: Path = DEV_DB_PATH) -> list[str]:
    with get_connection(db_path) as conn:
        return [row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]


def create_daily_backup_if_needed(db_path: Path = DEV_DB_PATH, backup_dir: Path = DB_BACKUP_DIR) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}-{datetime.now().strftime('%Y%m%d')}.db"
    if backup_path.exists():
        return backup_path
    with sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000) as source_conn:
        with sqlite3.connect(backup_path) as backup_conn:
            source_conn.backup(backup_conn)
    return backup_path


def add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def rebuild_print_films_table_if_needed(conn: sqlite3.Connection) -> None:
    indexes = conn.execute("PRAGMA index_list(print_films)").fetchall()
    has_unique_film_code = False
    for index in indexes:
        if not index["unique"]:
            continue
        index_name = index["name"]
        columns = [row["name"] for row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()]
        if columns == ["film_code"]:
            has_unique_film_code = True
            break
    if not has_unique_film_code:
        return
    conn.executescript(
        """
        ALTER TABLE print_films RENAME TO print_films_old;

        CREATE TABLE print_films (
            print_film_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            film_code TEXT NOT NULL,
            film_name TEXT NOT NULL,
            artwork_type TEXT NOT NULL DEFAULT '인쇄',
            revision_no TEXT NOT NULL,
            related_item_name TEXT,
            status TEXT NOT NULL DEFAULT '개발중',
            file_path TEXT,
            notes TEXT,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES development_projects(project_id)
        );

        INSERT INTO print_films (
            print_film_id, project_id, film_code, film_name, artwork_type, revision_no, related_item_name,
            status, file_path, notes, is_current, created_by, created_at
        )
        SELECT print_film_id, project_id, film_code, film_name, '인쇄', revision_no, related_item_name,
               status, file_path, notes, 1, created_by, created_at
        FROM print_films_old;

        DROP TABLE print_films_old;
        """
    )


def rebuild_experiment_samples_table_if_needed(conn: sqlite3.Connection) -> None:
    foreign_keys = conn.execute("PRAGMA foreign_key_list(experiment_samples)").fetchall()
    has_old_film_fk = any(row["from"] == "used_film_id" and row["table"] == "print_films_old" for row in foreign_keys)
    if not has_old_film_fk:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        ALTER TABLE experiment_samples RENAME TO experiment_samples_old;

        CREATE TABLE experiment_samples (
            sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_order_id INTEGER NOT NULL,
            sample_code TEXT NOT NULL UNIQUE,
            sample_seq INTEGER NOT NULL,
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

        INSERT INTO experiment_samples (
            sample_id, experiment_order_id, sample_code, sample_seq, sample_name, variation_note,
            mb_request_id, used_mold_id, used_film_id, customer_delivery_date, customer_result_date,
            customer_result, customer_result_notes, instruction_checks_json, instruction_detail_json,
            status, created_by, created_at
        )
        SELECT sample_id, experiment_order_id, sample_code, sample_seq, sample_name, variation_note,
               mb_request_id, used_mold_id, used_film_id, customer_delivery_date, customer_result_date,
               customer_result, customer_result_notes, instruction_checks_json, instruction_detail_json,
               status, created_by, created_at
        FROM experiment_samples_old;

        DROP TABLE experiment_samples_old;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def rebuild_sample_review_tables_if_needed(conn: sqlite3.Connection) -> None:
    targets = {
        "sample_op_reviews": """
            CREATE TABLE sample_op_reviews (
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
            )
        """,
        "sample_quality_reviews": """
            CREATE TABLE sample_quality_reviews (
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
            )
        """,
        "sample_final_reviews": """
            CREATE TABLE sample_final_reviews (
                sample_id INTEGER PRIMARY KEY,
                final_review_date TEXT,
                final_comment TEXT,
                final_action TEXT,
                approval_status TEXT NOT NULL DEFAULT '검토중',
                reviewed_by TEXT,
                reviewed_at TEXT,
                FOREIGN KEY(sample_id) REFERENCES experiment_samples(sample_id)
            )
        """,
    }
    tables_to_rebuild = []
    for table_name in targets:
        foreign_keys = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        if any(row["table"] == "experiment_samples_old" for row in foreign_keys):
            tables_to_rebuild.append(table_name)
    if not tables_to_rebuild:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    for table_name in tables_to_rebuild:
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {table_name}_old")
        conn.execute(targets[table_name])
        old_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name}_old)").fetchall()
        }
        new_columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        ]
        column_names = [column for column in new_columns if column in old_columns]
        select_columns = ", ".join(f'"{column}"' for column in column_names)
        conn.execute(f"INSERT INTO {table_name} ({select_columns}) SELECT {select_columns} FROM {table_name}_old")
        conn.execute(f"DROP TABLE {table_name}_old")
    conn.execute("PRAGMA foreign_keys = ON")


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def execute(sql: str, params: tuple = (), *, debug_label: str = "SQL") -> None:
    try:
        with get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
    except sqlite3.Error as exc:
        sql_preview = " ".join(sql.strip().split())[:200]
        db_path = resolve_db_path()
        LOGGER.exception("%s failed | db=%s | sql=%s | params=%s", debug_label, db_path, sql_preview, params)
        raise RuntimeError(f"{debug_label} 실행 실패 | DB={db_path} | {exc} | SQL={sql_preview}") from exc


def execute_insert(sql: str, params: tuple = (), *, debug_label: str = "SQL INSERT") -> int:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            return int(cur.lastrowid)
    except sqlite3.Error as exc:
        sql_preview = " ".join(sql.strip().split())[:200]
        db_path = resolve_db_path()
        LOGGER.exception("%s failed | db=%s | sql=%s | params=%s", debug_label, db_path, sql_preview, params)
        raise RuntimeError(f"{debug_label} 실행 실패 | DB={db_path} | {exc} | SQL={sql_preview}") from exc


def try_delete(sql: str, params: tuple = ()) -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            if int(cur.rowcount or 0) <= 0:
                return False, "삭제할 대상을 찾지 못했습니다."
        return True, "삭제했습니다."
    except sqlite3.IntegrityError:
        return False, "연결된 데이터가 있어서 삭제할 수 없습니다."


def save_uploaded_file(uploaded_file, upload_dir_or_subdir, subdir: str | None = None) -> str | None:
    if uploaded_file is None:
        return None
    if subdir is None:
        upload_dir = UPLOADS_DIR
        subdir_name = str(upload_dir_or_subdir)
    else:
        upload_dir = Path(upload_dir_or_subdir)
        subdir_name = subdir
    target_dir = upload_dir / subdir_name
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{uploaded_file.name}"
    path = target_dir / filename
    path.write_bytes(uploaded_file.getbuffer())
    return str(path)


def parse_revision_number(revision_text: str | None) -> int:
    if not revision_text:
        return 0
    cleaned = "".join(ch for ch in str(revision_text).upper() if ch.isdigit())
    return int(cleaned) if cleaned else 0


def format_revision(revision_number: int) -> str:
    return f"R{max(0, int(revision_number))}"


def latest_rows_by_code(
    df: pd.DataFrame,
    code_column: str,
    id_column: str,
    current_column: str | None = None,
) -> pd.DataFrame:
    if df.empty:
        return df
    work_df = df.copy()
    work_df["_revision_num"] = work_df["revision_no"].apply(parse_revision_number)
    sort_columns = [code_column]
    ascending = [True]
    if current_column and current_column in work_df.columns:
        sort_columns.append(current_column)
        ascending.append(False)
    sort_columns.extend(["_revision_num", id_column])
    ascending.extend([False, False])
    latest_df = work_df.sort_values(sort_columns, ascending=ascending).drop_duplicates(subset=[code_column], keep="first")
    return latest_df.drop(columns=["_revision_num"])
