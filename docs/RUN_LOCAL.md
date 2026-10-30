# 로컬 실행 가이드

## 1. 준비

```powershell
git clone -b claude/busy-volta-of5gyv https://github.com/HaileyHYoo/intersection_diagnostic.git
cd intersection_diagnostic
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env      # 챗봇 .env 값(InfluxDB, Neo4j, OpenAI)을 그대로 넣으면 됩니다
```

`.env`에는 `TOMTOM_API_KEY`도 넣어 주세요(챗봇 TomTom 기능과 같은 키). 대기행렬 조회에 씁니다.

OpenAI 키가 없거나 `--no-llm`을 주면 D001/D002 문장은 코드가 직접 씁니다. 숫자와 판정은 어느 경우든 코드가 계산합니다.

## 2. 가짜 데이터로 전체 흐름 확인

```powershell
python main.py --no-llm demo --serve
```

- 48개 가상 교차로(멜번 CBD 근처)를 스크리닝하고, 시나리오별로 의도한 분류가 나오는지 확인합니다.
  - Red 4, Amber 2, Grey 4, Detector Health 1, Normal
- 첫 번째 Red 교차로의 리포트를 화면에 출력합니다.
- `out/demo_map.html`을 만듭니다. 서버 없이 파일만 열어도 근거를 볼 수 있습니다.
- `--serve`를 주면 http://127.0.0.1:8765 에서 지도를 띄웁니다. Red를 클릭하면 D001 + D002가 실행됩니다.

## 3. 실데이터 점검 (먼저 해 주세요)

```powershell
python main.py inspect --site 4397 --end 2026-10-27T08:30 --hours 2
```

화면 요약과 `out/inspect_S4397_<시각>.json`이 나옵니다. 아래 항목을 확인합니다(자세한 내용은 SCHEMA.md).

| 확인할 것 | 보는 곳 |
|---|---|
| `d[n]`의 n이 Neo4j `detector_number`와 같은지 | `checks.detectors`에서 `active_without_field`와 `fields_without_neo4j_detector`가 모두 비어 있으면 일치 |
| `scats/volume` 값 타입 | `feeds.detector_counts.value_types` |
| 타임스탬프가 구간 끝 기준인지 | 각 feed의 `last`가 창 끝 시각과 같은지 |
| 정각에서 벗어난 기록의 패턴 | `offset_within_step`, `on_grid` |
| EGRESS 링크에 볼륨과 GreenShare가 있는지 | `checks.links` |
| TomTom 매핑과 대기행렬 아카이브가 읽히는지 | `checks.tomtom` (화면 요약의 `tomtom:` 줄) |

결과에 따라 `diagnostics/config/schema.json`이나 `rules.json`의 값만 바꾸면 됩니다. 코드는 고치지 않아도 됩니다.

## 4. 실데이터 스크리닝과 지도

```powershell
python main.py map                                    # http://127.0.0.1:8765, 최근 30분
python main.py screen --end 2026-05-12T08:30          # 과거 구간(그 날짜 이전 8주가 기준)
python main.py summary                                # 최근 실행에서 분류별 원인 집계(Detector Health, Grey, Amber)
python main.py diagnose --run <run_id> --site 4397    # Red 교차로 리포트
python main.py export-html --run <run_id> --out out/map.html
python main.py baseline --days 7                      # 주간 베이스라인 미리 계산
```

- 시각에 오프셋이 없으면 멜번 현지 시각으로 봅니다.
- 처음 실행할 때는 8주치 기준 구간을 조회하므로 시간이 걸릴 수 있습니다. 이후에는 SQLite(`diagnostics.sqlite3`)에 캐시된 값을 씁니다.

## 5. 규칙 바꾸기

`diagnostics/config/rules.json`에 모든 기준값과 스위치가 있습니다.

| 항목 | 기본값 |
|---|---|
| Q2 최소 대수 | `q2.min_vehicles` 10 |
| 퍼센트 기준 | `q1.min_pct_difference` 10 |
| 녹색 없는 접근로가 있으면 Grey | `q3c.grey_site_if_any_approach_without_green` true |
| 볼륨 없는 접근로가 있으면 Grey | `q1.grey_if_any_approach_missing` true |
| 히스토리 제외일 | `history.exclude` (공휴일, 서머타임 변경일, 연말) |
| 데이터 지연 여유 | `data_latency_minutes` 5 |
| 클릭 시 실행할 템플릿 | `click` (Red만 D001, D002) |
| 평소값 기준 | `reference_value` `"median"` (중앙값, 프로덕션 계약 기준) |
| TomTom 대기행렬(API) | `tomtom.api_enabled` true (문서 13장). `.env`에 `TOMTOM_API_KEY` 필요. 없으면 대기행렬만 "unavailable" |
| 프로덕션 템플릿 ID | `contract.template_ids` (D002 ID는 확인 전 임시값) |

규칙이나 스키마 버전이 바뀌면 베이스라인과 실행 결과를 자동으로 새로 계산합니다.

## 6. 프로덕션 패키지 만들기

```powershell
python tools/build_production.py          # production/ 생성 + import 확인
python tools/build_production.py --check  # 소스와 일치하는지 확인
```
