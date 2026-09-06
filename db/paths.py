from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DEV_DB_PATH = APP_DIR / "development_management.db"
DB_BACKUP_DIR = APP_DIR / "backups"
UPLOADS_DIR = APP_DIR / "uploads"
LOCAL_COST_APP_PATH = APP_DIR / "ui_apps" / "cost_legacy_app.py"

TEMPLATES_DIR = APP_DIR / "templates"
GENERATED_DIR = APP_DIR / "generated"
CUSTOMER_FORMS_DIR = GENERATED_DIR / "customer_forms"
CUSTOMER_FORMS_PDF_DIR = GENERATED_DIR / "customer_forms_pdf"

KOREAN_FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/malgun.ttf"),  # Windows
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),  # macOS
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),  # Linux (나눔고딕 설치 시)
]


def find_korean_font() -> Path | None:
    for candidate in KOREAN_FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None
