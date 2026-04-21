from __future__ import annotations

import os

from domain.constants import APP_GROUP_SETS
from services.app_runner_service import run_app


def main() -> None:
    print("RUNNING FILE =", __file__)
    print("CWD =", os.getcwd())
    run_app(
        page_title="플라스틱 포장재 개발관리 - 개발",
        group_names=APP_GROUP_SETS["dev"],
        page_config_key="dev",
    )
