from __future__ import annotations


ROLE_LABELS = {
    "admin": "관리자",
    "sales": "영업",
    "developer": "사내개발자",
    "op": "공정 OP",
    "quality": "품질",
    "mold": "금형담당",
    "mb": "MB담당",
    "film": "원화담당",
}

PAGE_PERMISSIONS = {
    "프로젝트 기본정보": {"admin", "sales", "developer"},
    "상품": {"admin", "sales", "developer"},
    "공정품": {"admin", "developer"},
    "제품구성": {"admin", "developer"},
    "구조조회": {"admin", "sales", "developer", "op", "quality", "mold", "mb", "film"},
    "제품도면": {"admin", "developer"},
    "금형 기본정보": {"admin", "mold"},
    "금형 출고입고": {"admin", "mold", "developer"},
    "원화": {"admin", "film"},
    "원재료": {"admin", "developer", "mb"},
    "부재료": {"admin", "developer"},
    "MB 의뢰": {"admin", "developer", "mb"},
    "MB 구매입고": {"admin", "developer", "mb"},
    "공정품 요구": {"admin", "sales", "developer"},
    "조립품 요구": {"admin", "sales", "developer"},
    "사출 실험지시": {"admin", "op", "developer"},
    "공정품 실험지시": {"admin", "sales", "op", "developer"},
    "조립 실험지시": {"admin", "sales", "op", "developer"},
    "실험지시": {"admin", "op", "developer"},
    "WMS_공정품": {"admin", "developer", "op"},
    "실험": {"admin", "op"},
    "사출실험": {"admin", "op"},
    "품질검토": {"admin", "quality"},
    "최종검토": {"admin", "developer"},
    "사용자관리": {"admin"},
    "역할관리": {"admin"},
}

MENU_GROUPS = {
    "기본정보관리": ["프로젝트 기본정보", "상품", "공정품", "제품구성", "제품도면", "원화", "원재료", "부재료"],
    "실행관리": ["금형 기본정보", "금형 출고입고", "MB 의뢰", "MB 구매입고", "WMS_공정품"],
    "개발진행": ["공정품 요구", "조립품 요구", "사출 실험지시", "공정품 실험지시", "조립 실험지시", "실험", "품질검토", "최종검토"],
    "현황조회": ["대시보드", "구조조회"],
    "시스템관리": ["사용자관리", "역할관리"],
}

COST_TOOL_MENU_GROUPS = {
    "원가관리도구": ["기초정보", "사전견적 시뮬레이션", "시뮬레이션", "History"],
}

ROLE_MENU_GROUPS = {**MENU_GROUPS, **COST_TOOL_MENU_GROUPS}

APP_GROUP_SETS = {
    "all": list(MENU_GROUPS.keys()),
    "admin": ["기본정보관리", "시스템관리"],
    "dev": ["개발진행", "실행관리", "현황조회"],
}

INJECTION_STAGE_GROUPS = [
    (
        "사출",
        10,
        [
            ("속도", "사출_속도"),
            ("압력", "사출_압력"),
            ("거리", "사출_거리"),
        ],
    ),
    (
        "보압",
        3,
        [
            ("속도", "보압_속도"),
            ("압력", "보압_압력"),
            ("시간", "보압_시간"),
        ],
    ),
    (
        "계량",
        4,
        [
            ("RPM", "계량_RPM"),
            ("거리", "계량_거리"),
            ("배압", "계량_배압"),
        ],
    ),
]

INJECTION_EXTRA_GROUPS = [
    ("보압 보조", ["쿠션"], 1),
    ("계량 보조", ["석백 전", "석백 후"], 2),
    ("실린더 온도", ["실린더_NH", "실린더_N1", "실린더_N2", "실린더_N3", "실린더_N4"], 5),
    ("금형 온도", ["금형온도_고정", "금형온도_이동"], 2),
    ("H/R 번호 / 온도", [f"H/R_번호{i}" for i in range(1, 5)] + [f"H/R_온도{i}" for i in range(1, 5)], 4),
    ("온도 특이사항", ["금형온도_특이사항", "H/R_특이사항"], 2),
    ("Cycle Time", ["사출(충진)_1차", "냉각_1차", "회전_1차", "C/T_1차", "사출(충진)_2차", "냉각_2차", "회전_2차"], 4),
    ("작업 메모", ["취출방법", "문제점_현상", "개선사항"], 3),
]

MEASUREMENT_SLOT_KEYS = ["A", "B", "C"]
MEASUREMENT_REPEAT_COUNT = 8


ITEM_CLASSES = ["공정품"]
ITEM_TYPES = [
    "사출품",
    "증착품",
    "코팅품",
    "인쇄품",
    "사상품",
    "조립품",
    "완제품",
]

RAW_MATERIAL_TYPES = ["원료"]
SUB_MATERIAL_TYPES = ["바킹", "라벨", "박스", "기타"]
MB_STATUS_OPTIONS = ["개발중", "시험중", "확정", "사용중지"]
MATERIAL_STATUS_OPTIONS = ["사용중", "중지"]
DRAWING_TYPES = ["제품도면"]
MOLD_DRAWING_LAYOUTS = ["1CAV", "2CAV", "4CAV", "기타"]
MOLD_STATUS_OPTIONS = ["개발중", "사용가능", "수정중", "보관", "폐기"]
FILM_STATUS_OPTIONS = ["개발중", "사용가능", "변경예정", "폐기"]
ARTWORK_TYPE_OPTIONS = ["인쇄", "라벨"]
PROJECT_STATUS_OPTIONS = ["초기등록", "개발중", "표준확정", "양산이관", "종료"]
PROJECT_DEVELOPMENT_TYPE_OPTIONS = ["신규금형", "리뉴얼", "원가", "기타"]
REQUIREMENT_CHECK_OPTIONS = ["특정부분규격", "무게", "색상", "내스크래치", "분리", "기능규격"]
INSTRUCTION_CHECK_OPTIONS = ["준비점검", "조건입력", "1차측정", "수정안", "2차측정", "24시간후", "후가공", "조립"]
EXPERIMENT_PROCESS_OPTIONS = ["사출", "인쇄", "후가공", "사상", "조립"]
MILESTONE_OPTIONS = ["", "test0", "test1", "색상표준", "표준견본", "시험평가"]
SAMPLE_RESULT_OPTIONS = ["대기", "적합", "조건부적합", "보완필요", "재시험", "부적합"]
DRAWING_RECEIPT_STATUS_OPTIONS = ["입수완료", "미입수"]
COLOR_NUANCE_OPTIONS = ["", "연함", "표준", "진함", "기타"]
MOLD_UPDATE_TYPE_OPTIONS = ["", "치수", "외관", "게이트", "취출", "냉각", "기타"]
VENDOR_RESELECTION_OPTIONS = ["없음", "단가", "납기", "품질", "대응성", "기타"]
ASSEMBLY_FUNCTION_OPTIONS = ["", "조립성", "체결력", "작동성", "유격", "강도", "기타"]
SUB_MATERIAL_ISSUE_OPTIONS = ["", "바킹", "라벨", "박스", "기타"]
