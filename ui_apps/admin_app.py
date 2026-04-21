from __future__ import annotations

from domain.constants import APP_GROUP_SETS
from services.app_runner_service import run_app


def main() -> None:
    run_app(
        page_title="플라스틱 포장재 개발관리 - 관리자",
        group_names=APP_GROUP_SETS["admin"],
        page_config_key="admin",
    )
