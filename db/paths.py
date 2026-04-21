from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DEV_DB_PATH = APP_DIR / "development_management.db"
DB_BACKUP_DIR = APP_DIR / "backups"
UPLOADS_DIR = APP_DIR / "uploads"
LOCAL_COST_APP_PATH = APP_DIR / "ui_apps" / "cost_legacy_app.py"
