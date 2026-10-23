# 개발프로세스(플라스틱 포장재 개발관리) PROGRAM_NOTES
최종 갱신: 2026-10-23 / 작성: Claude(AI) 보조 작성 — 사람 검토자 서명 필요

## 1. 한 줄 요약
플라스틱 포장재(화장품 용기 등) 신제품 개발 과정 — 프로젝트 등록부터 고객요구, 실험지시, 실험, 품질검토, 최종검토(양산 확정)까지 — 을 영업/개발/공정OP/품질 담당자가 함께 기록·추적하는 사내 웹 업무 시스템.

## 2. 실행 방법과 위치

- 폴더: `D:\Sunil_Project\개발프로세스` (서버 PC). 같은 경로가 `\\192.168.15.143\Sunil_Project\개발프로세스` 공유 폴더로도 접근됨.
- 기술 스택: Python 3.11.9 / Streamlit 1.58.0 (웹 UI) / SQLite3(표준 라이브러리, 별도 DB 서버 없음) / pandas 2.2.2 / Playwright 1.58.0(PDF 생성용 Chromium) / reportlab 4.4.10 / openpyxl 3.1.5
- 하나의 코드베이스에서 **3개의 독립된 Streamlit 앱**을 각각 다른 포트로 띄움:

| 앱 | 진입 파일 | 포트 | 실행 배치파일 | 메뉴 범위 |
| --- | --- | --- | --- | --- |
| 개발 | `ui_apps/dev_app.py` | 8501(Streamlit 기본값, 별도 설정 없음) | `개발실행.bat` | 개발진행 / 실행관리 / 현황조회 |
| 관리자 | `ui_apps/admin_app.py` | 8506 | `관리자모드실행.bat` | 기본정보관리 / 시스템관리 |
| 원가계산 | `ui_apps/cost_app.py` | 8507 | `비용계산기실행.bat` | 원가관리도구(레거시, 이번 작업 범위 밖) |

- 모두 `--server.address 0.0.0.0`으로 띄워 같은 네트워크의 여러 PC에서 접속 가능.
- 로그인 필요. `users` 테이블(비밀번호는 해시 저장) + `user_sessions`(토큰 해시, 세션 497건 — 활발히 쓰이고 있음을 보여줌).
- 역할(role_code): `admin, sales, developer, op, quality, mold, mb, film`이 `domain/constants.py`에 정의돼 있으나, 실제 DB `roles` 테이블에는 `mb, film`이 없고 대신 `supporter(진행관리자)`가 있음 — **코드와 DB 정의가 불일치**(10번 항목 참고).
- 코드 수정 후 서버 프로세스를 재시작하지 않아도 Streamlit 자체 감지로 반영되는 것을 실사용 중 확인함(2026-10-23).

## 3. 데이터 입력 (어디서 가져오나)

| 입력 | 형식/위치 | 가져오는 방법 | 주기 |
| --- | --- | --- | --- |
| 프로젝트/상품/공정품/요구/실험/검토 등 업무 데이터 | 웹 화면 입력폼 → SQLite | 담당자가 화면에서 직접 입력 후 저장 버튼 | 상시(수시) |
| 제품도면/금형도면/원화 파일 | PDF·이미지, `uploads/product_drawings` 등 | 화면에서 파일 수동 업로드 | 필요시 |
| 외부 시스템(스마트시스템 등)의 기존 품목/BOM | 현재 자동 연동 없음 | **(추정) 수동으로 "공정품" 화면에 다시 입력** | 필요시 — 9·10번 항목에 개선 방향 기록 |

## 4. 데이터 저장 (무엇을 저장하나)

- SQLite 파일: `development_management.db` (프로젝트 루트), 1.4MB(2026-10-23 기준)
- 백업: `backups/development_management-YYYYMMDD.db` — **하루 1회, 해당 날짜 파일이 없을 때만** 앱 기동 시 자동 생성(`db/runtime.py: create_daily_backup_if_needed`). 2026-10-09~10-23 백업 10개 확인됨.

주요 테이블(2026-10-23 기준 건수):

| 테이블 | 용도 | 기본/식별키 | 건수 |
| --- | --- | --- | --- |
| `development_projects` | 프로젝트(고객·제품 단위) | `project_id`(PK), `project_code`(UNIQUE) | 22 |
| `products` | 프로젝트 안의 "상품"(완제품 단위), `root_item_id`로 최종 공정품 연결 | `product_id`(PK), `product_code`(UNIQUE) | 34 |
| `items` | 공정품(부품) 마스터 — **프로젝트/상품에 종속되지 않는 공용 마스터**(2026-08-27 변경) | `item_id`(PK), `item_code`(전체 UNIQUE) | 84 |
| `item_bom` | 품목 간 상위-하위 연결(BOM), 특정 프로젝트 소유 | `bom_id`(PK), `project_id`+`parent_item_id`+`child_item_id` | 57 |
| `experiment_orders` | 공정품요구/조립품요구 | `experiment_order_id`(PK), `order_code`(UNIQUE) | 128 |
| `experiment_instructions` | 실험지시 | `experiment_instruction_id`(PK), `instruction_code`(UNIQUE) | 66 |
| `experiment_samples` | 실험(샘플) | `sample_id`(PK), `sample_code`(UNIQUE) | 39 |
| `sample_op_reviews` / `sample_quality_reviews` / `sample_final_reviews` | 실험/품질검토/최종검토 결과(샘플 1:1) | `sample_id`(PK) | 39 / 12 / 6 |
| `meta_requirements` / `meta_requirement_lines` | 조립품요구의 트리(메타) 구조 | `meta_requirement_id`(PK) | 20 / 75 |
| `product_drawings` / `mold_drawings` / `molds` | 제품도면 / 금형도면 / 금형 | 각자 PK | 67 / 48 / 45 |
| `postprocess_item_moves` | WMS(공정품 출고입고) | `postprocess_move_id`(PK), `move_code`(UNIQUE) | 200 |
| `mb_requests` / `mb_receipts` / `mb_materials` | MB(원료) 의뢰·입고 | 각자 PK | 7 / 2 / 1 |
| `raw_materials` / `sub_materials` / `print_films` | 원재료 / 부재료 / 원화(인쇄필름) 마스터 | 각자 PK | 23 / 2 / 3 |
| `users` / `roles` / `user_roles` / `user_sessions` | 로그인·권한 | — | 9 / 7 / 18 / 497 |
| `role_menu_permissions` | 역할별 메뉴 접근 권한 | `(role_code, menu_group, menu_name)` | 66 |
| `cost_simulation_headers/lines`, `simulation_headers/lines`, `resource_rates`, `pre_estimate_*` | 원가관리도구(레거시, 별도 UI) 데이터 | — | 대부분 0~9, 거의 미사용 |

## 5. 데이터 출력 (어디로 보내나)

| 출력 | 형식/위치 | 누가 쓰나 |
| --- | --- | --- |
| 최종검토 고객 발송용 리포트 | PDF(A4 세로), `generated/customer_forms_pdf` | 영업 담당 → 고객 |
| 현황조회(대시보드/구조조회) | 웹 화면(Streamlit) | 전체 담당자 |
| 담당자별 체크리스트(이번 대화에서 생성) | Claude Docs 문서(외부 링크) | 각 담당자 |
| (제안, 미구현) 양산 확정 품목/BOM 내보내기 | 미정 | 스마트시스템/ERP 담당 — 9·10번 항목 참고 |

## 6. 핵심 키와 코드 체계

| 코드 | 생성 규칙 | 범위 |
| --- | --- | --- |
| `project_code` | 자유 텍스트 입력 | 전체 UNIQUE. 프로젝트 삭제 전까지 안전하게 수정 가능(내부 연결은 `project_id`로 되어 있어 코드 변경이 다른 데이터를 깨뜨리지 않음 — 2026-10-23 확인) |
| `product_code` | 자유 텍스트 입력 | 전체 UNIQUE |
| `item_code` | 자유 텍스트 입력(신규 등록 시 수동 지정) | **전체 UNIQUE, 프로젝트와 무관한 공용 식별자.** 이 코드가 `order_code`/`instruction_code`/`sample_code` 안에 문자 그대로 복사되어 들어가므로, **등록 후에 바꾸면 안 됨**(project_code와 달리 안전하지 않음 — 7번 항목 참고) |
| `order_code` | `RQ-{item_code}[-R{리비전변형}][M]-{YYYYMMDD}-{일자별 순번}` | 공정품요구/조립품요구 1건당 1개 |
| `instruction_code` | `order_code`의 `RQ-`를 `IN-`으로 치환 + `-{해당 요구의 지시 순번:02d}` | 실험지시 1건당 1개 |
| `sample_code` | `instruction_code`의 `IN-`을 `EX-`로 치환 (추정: 동일 패턴) | 실험(샘플) 1건당 1개 |
| `move_code` | `WMS-{postprocess_move_id:06d}` | WMS 출고입고 1건당 1개 |
| `meta_code`, `dispatch_code`, `request_code`(MB) | 각 서비스 코드에서 유사한 규칙으로 생성 | 각 업무 1건당 1개 |

품목 공정유형(`items.process_type`): `사출 / 인쇄 / 후가공 / 사상 / 조립` — 이 값이 어떤 요구·실험지시·실험 화면으로 흐를지를 결정하는 핵심 분기값.

## 7. 핵심 계산 규칙

- **진행 단계 상태 판정**(`ui_apps/system_pages.py: _timeline_display_status`): 지시 없음→`지시 대기`, 지시만 있음→`지시 생성`, 샘플 있으나 실험일 없음→`실험 대기`, 실험일 있으나 품질검토일 없음→`품질 검토 대기`, 품질검토일 있으나 최종검토일 없음→`최종검토 대기`, 그 이후는 `approval_status`(검토중/재실험/수정지시/표준후보/확정) 값 그대로 노출.
- **최종검토 확정 제한**: `drawing_receipt_status`(도면 입수 상태)가 `미입수`이면 `approval_status`를 `확정`으로 저장할 수 없음(강제 검증, `development_pages.py`).
- **공정품요구 화면에서 "요구 가능한 품목" 산출 규칙**: 상품에 지정된 `root_item_id`(최종 공정품)에서 `item_bom`을 타고 내려가며 전체 하위 품목을 재귀로 모음(`services/reference_data_service.py: project_item_tree_options`). **BOM 연결이 없으면 최종 공정품 자기 자신만 요구 가능** — 하위 부품 단위 요구는 BOM 연결 전에는 불가능.
- **공용 품목 집계 규칙(2026-10-21 변경)**: 대시보드·구조조회·실험/품질검토/최종검토의 품목 선택 등은 "품목 자신의 소속 프로젝트"가 아니라 "그 품목이 실제로 쓰인 요구(`experiment_orders`)·BOM(`item_bom`) 레코드의 `project_id`"를 기준으로 역추적해 집계함. 자세한 이유는 9번 항목.
- 원가(원가관리도구) 계산 로직은 이번 조사 범위에 포함하지 않음(미확인).

## 8. 다른 프로그램과의 연결

| 상대 프로그램 | 주고받는 데이터 | 방향 | 연결 방식 | 상태 |
| --- | --- | --- | --- | --- |
| 스마트시스템(ERP/MES로 추정, 이름만 언급됨) | 품목코드(item_code), BOM(item_bom), 상품코드(product_code) | 이 시스템 → 스마트시스템(내보내기) | 미정(제안: 엑셀/API) | **미구현 — 설계 방향만 합의(9번 항목)** |

현재 이 프로그램은 **다른 시스템과 자동으로 연결되어 있지 않음.** 기존에 스마트시스템 등에 이미 등록된 품목을 쓰려면 지금은 "공정품" 화면에 사람이 직접 다시 입력해야 함(추정 — 가져오기 기능 없음).

## 9. 결정 사항과 이유

| 날짜 | 결정 | 이유 | 결정한 사람 |
| --- | --- | --- | --- |
| 2026-08-27 | 공정품(품목)을 프로젝트/상품에서 분리해 독립 마스터로 전환(`feat: BOM 기반 공용 공정품 지원`) | 같은 부품을 여러 프로젝트가 재사용할 때마다 중복 등록해야 하는 문제를 없애려고 | 이전 세션(이 대화 밖) |
| 2026-09-07 | 상품 저장 시 "최종 공정품" 지정을 필수화 | 지정 안 하면 이후 실험/지시 단계에서 구조 조회가 전혀 안 되는 문제 발생 | 이전 세션(이 대화 밖) |
| 2026-10-18~21 | 대시보드/구조조회/실험·품질검토·최종검토 품목선택/WMS/메타트리 총 6곳의 "품목 자신의 project_code 기준 필터"를 "요구·BOM 레코드의 project_id 기준"으로 통일 수정 | 공용 품목으로 전환된 품목들의 요구·실험 이력이 해당 화면들에서 통째로 안 보이는 회귀 버그였음(A6937 프로젝트 기준 요구 30건 중 24건이 안 보였음) | 이번 대화 |
| 2026-10-21 | 최종검토 PDF를 A4 세로형으로, Playwright를 ProactorEventLoop로 실행 | Windows+Streamlit(Tornado) 환경에서 Playwright가 서브프로세스 실행 불가 오류를 내고, PDF가 가로형으로 찌그러져 나오던 문제 | 이번 대화 |
| 2026-10-21 | 공정품요구 화면에 "선행조건 점검 패널"(프로젝트/상품/최종공정품/BOM 단계별 ✅❌) 시범 추가 | 사용자가 "안 되는 이유를 바로 알고 담당자에게 요청할 수 있게" 요청 | 이번 대화 |
| 2026-10-23(제안, 미구현) | 스마트시스템 연동은 **단방향(이 시스템→스마트시스템) 내보내기**로, `item_code`를 공유 키로 삼는 구조를 제안 | 양방향 전체 동기화는 유지보수 부담이 크고, `item_code`는 생성된 요구/지시/샘플 코드에 문자 그대로 박혀 있어 나중에 바꾸면 위험하므로, 처음부터 스마트시스템 코드와 같은 값으로 등록하는 쪽을 권장 | 이번 대화(사람 확정 필요) |

## 10. 알려진 문제와 할 일

- **역할 정의 불일치**: `domain/constants.py`의 `ROLE_LABELS`에는 `mb, film`이 있으나 실제 `roles` 테이블엔 없고, 대신 테이블에만 있는 `supporter(진행관리자)`는 코드에 정의가 없음. 화면에 역할명이 코드 그대로 노출될 수 있음.
- **스마트시스템 연동 미구현**: 기존 품목을 가져오는 기능, 양산 확정 품목을 내보내는 기능 모두 없음. 지금은 사람이 수동으로 "공정품" 화면에 재입력해야 함. (9번 항목 제안 방향 참고)
- **"최종 공정품" 미지정 상품 9건 존재**(2026-10-21 확인 당시 기준, 변동 가능): 해당 상품에 공용 품목을 연결하면 메타요구 트리에서 누락될 수 있어, 관리자가 들어가 지정해두는 것을 권장.
- **선행조건 점검 패널은 공정품요구 화면에만 시범 적용됨**: 실험지시/실험/품질검토/최종검토 화면까지 확장할지는 미결정.
- **중복 계정으로 추정되는 로그인**: `admin`/`a`/`kimyumi` 3개 계정이 모두 `admin` 역할로 존재(실사용·테스트용 구분 불명확, 추정).
- **원가관리도구(cost_app.py)는 이번 조사·수정 범위에서 제외** — 데이터도 거의 비어 있어(0~9건) 실사용 여부 불확실(추정).
- `services/ui_apps/`, `db/paths_260802.py`, `services/development_runtime_service_260802.py`, `domain/domain/` 폴더는 **실제 앱이 쓰지 않는 중복/백업 복사본**(확인됨). 혼동 방지를 위해 정리 권장.

## 11. 하드코딩된 값

- 기본 관리자 계정명 `admin`(비밀번호는 기록하지 않음, `db/schema.py`에서 최초 1회 생성)
- 설비 일일 사용료(`resource_rates` 테이블, 코드 아님, DB 데이터): IMC-350/300/280/250/200톤 사출기 요율 — 원가관리도구에서 사용(추정)
- 한글 폰트 경로 후보(`db/paths.py: KOREAN_FONT_CANDIDATES`): `C:/Windows/Fonts/malgun.ttf` 등 OS별 고정 경로
- 그 외 거래처코드·공장명 등 업무성 하드코딩 값은 코드 검색상 발견되지 않음(확인됨)

## 12. 백업과 복구

- SQLite 파일 자체 백업: `backups/development_management-YYYYMMDD.db`, 하루 1회(그날 첫 접속 시) 자동 생성, 별도 삭제 로직 없음(계속 쌓임 — 용량 관리 필요할 수 있음, 추정).
- Git 저장소: 코드는 GitHub(`dustincosmos/development-process`)에서 버전 관리됨. DB 파일(`*.db`)과 업로드 파일(`uploads/`, `generated/`, `backups/`)은 `.gitignore`로 제외되어 **코드 백업과 데이터 백업이 분리되어 있음**.

## 13. 변경 이력

| 날짜 | 버전 | 변경 내용 |
| --- | --- | --- |
| 2026-08-27 | - | 공정품-프로젝트 분리(공용 품목) 아키텍처 도입 |
| 2026-09-07 | - | 상품 "최종 공정품" 필수화, 로그인 화면 보안 문구 정리 |
| 2026-10-18 | - | 제품도면 연계 조회의 공용 품목 누락 버그 수정 |
| 2026-10-21 | - | 최종검토 PDF(세로형/Playwright) 수정, 공용 품목 조회 누락 5곳 수정, 선행조건 점검 패널(시범) 추가 |
| 2026-10-23 | - | 이 문서(PROGRAM_NOTES.md) 최초 작성, 스마트시스템 연동 설계 방향 제안 |

> 이 파일은 데이터 구조나 계산 규칙이 바뀔 때마다 함께 수정해야 합니다.
