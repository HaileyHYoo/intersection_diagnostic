# `python main.py stats` – 점검 항목 정의

`stats`는 **모든 교차로(2,501곳)에 대해 각 점검을 서로 독립적으로** 셉니다. 스크리닝은 단계를 거칩니다. Q2(검지기)를 통과해야 Q1/Q3를 보고, 데이터가 하나라도 빠지면 Grey가 됩니다. 반면 여기서는 단계와 상관없이 각 항목을 따로 판정합니다. 예를 들어 "현재 KPI 없음"에는 검지기 문제로 Detector Health가 된 교차로도 포함됩니다.

공통 사항:
- **분석 기간:** 스크리닝과 같은 30분(예: 금 15:00–15:30)이며, 15분 구간 두 개로 이루어집니다. **"현재 값이 있다"는 두 15분 구간 모두에 값이 있다는 뜻**이고, 하나라도 빠지면 "없음"입니다.
- **기준 주:** 스크리닝과 같습니다. 이전 8주의 같은 요일·같은 30분에서 공휴일 등 제외일을 뺀 주입니다(예: 7주).
- **"이력 부족":** 기준 주 가운데 유효한 값이 있는 주가 5주 미만이라는 뜻입니다(`history.min_observations`).
- **평가 대상 접근로:**
  - Q1: 기준 주 중 한 주라도 교통량이 있었던 EGRESS 링크
  - Q3C: 기준 주 중 한 주라도 녹색 비율이 있었던 링크
- 각 열은 교차로마다 **1 = 해당 문제가 있음, 0 = 없음**입니다. 한 교차로가 여러 항목에 동시에 1일 수 있습니다.

## 1. 데이터 점검 (1 = 문제 있음)

### 검지기 (Q2 입력: `scats/volume`의 `d[n]`, Neo4j `Detector`)

| 열 | 정의 |
|---|---|
| `no_active_detector` | Neo4j에서 이 교차로에 `BELONG_TO`로 연결된 `active = true` 검지기가 하나도 없음 |
| `detector_records_missing` | 활성 검지기 중 하나 이상이 **60분 합계가 10대 미만**이면서 5분 기록 12개 중 일부가 빠졌거나 음수임 (판정: INSUFFICIENT). 기록이 빠졌어도 합계가 10대 이상이면 통과이므로 여기에 세지 않음 |
| `all_detector_records_missing` | 활성 검지기는 있지만, 60분 동안 모든 검지기의 유효한 5분 기록이 0개 |
| `detector_below_threshold` | 활성 검지기 중 하나 이상이 5분 기록 12개가 모두 있는데 60분 합계가 10대 미만 (판정: FAIL → Detector Health Issue) |

### 교통량 (Q1 입력: `scats-aggregation/volume`, `DetectorGroupId` = EGRESS `link_id`)

| 열 | 정의 |
|---|---|
| `no_egress_link` | Neo4j에 이 교차로의 `EGRESS` 도로(`link_id` 있음)가 하나도 없음 |
| `link_without_volume_history` | EGRESS 링크 중 하나 이상이 기준 주 어느 주에도 30분 교통량이 없음. 이 링크는 Q1 평가에서 빠짐 |
| `link_without_current_volume` | 평가 대상 링크 중 하나 이상이 이번 30분 교통량이 없음(15분 구간 하나라도 없으면 해당) |
| `link_short_volume_history` | 평가 대상 링크 중 하나 이상이 이번 교통량은 있지만, 유효한 과거 교통량이 5주 미만 |

### 주기 KPI (Q3A/Q3B 입력: `IntersectionPerfKpi`)

| 열 | 정의 |
|---|---|
| `no_current_cycle_length` | 이번 30분에 `AvgCycle` 값이 없음(15분 구간 하나라도 없으면 해당) |
| `no_current_cycle_stability` | 이번 30분에 `CycleStability` 값이 없음 |
| `short_kpi_history` | 주기 길이 또는 주기 안정도가 **이번 값은 있지만** 과거 값이 5주 미만. 이번 값이 없는 교차로는 위 두 열에서 세고 여기서는 세지 않음 |

### 위상 서비스 (Q3C 입력: `IntersectionPerfApproach`의 `GreenShare`, `HasGreen`)

| 열 | 정의 |
|---|---|
| `no_perf_approach_now` | 이번 30분에 이 교차로의 `IntersectionPerfApproach` 기록이 어느 링크에도 없음 |
| `no_phase_service_history` | 기준 주 어느 주에도 유효한 녹색 비율(HasGreen = 1)이 있었던 링크가 없음. 평가할 접근로가 없으므로 Q3C 평가 불가 |
| `approach_hasgreen_0` | 평가 대상 접근로 중 하나 이상이 두 15분 구간에 기록은 있지만, 하나 이상에서 `HasGreen = 0` (실제로 기록된 "녹색 없음") |
| `approach_no_green_record` | 평가 대상 접근로 중 하나 이상이 15분 구간 하나 이상에서 `GreenShare`/`HasGreen` 기록 자체가 없음 (결측) |
| `approach_short_green_history` | 평가 대상 접근로 중 하나 이상이 이번 녹색 비율은 있지만, 과거 유효 녹색 비율이 5주 미만 |

### TomTom

| 열 | 정의 |
|---|---|
| `no_tomtom_mapping` | 검증된 TomTom 접근로 ↔ 링크 매핑 파일에 이 교차로의 접근로가 없음. Q5 확인이 불가능하고, 스크리닝 분류에는 영향 없음 |

**`sites_without_any_screening_data_problem`:** TomTom 매핑을 제외한 위 데이터 점검 16개에 하나도 해당하지 않는 교차로 수입니다.

## 2. 질문별 단독 결과 (모든 교차로)

각 질문을 다른 질문과 상관없이 모든 교차로에 적용한 판정입니다. 판정 규칙은 스크리닝과 같습니다(METHOD.md).

| 열 | 값과 정의 |
|---|---|
| `q2` | PASS / FAIL / INSUFFICIENT DATA. 검지기 게이트 판정(위 검지기 항목 참고) |
| `q1` | NORMAL / ABNORMAL / INSUFFICIENT DATA. 평가 대상 링크 중 하나라도 이상(10–90 백분위 범위 밖이면서 평소보다 10% 이상 차이)이면 ABNORMAL. 이상이 없는데 빠진 링크가 있으면 INSUFFICIENT |
| `q3a_cycle_length` | 주기 길이가 범위 밖이면서 평소보다 10% 이상 차이 나면 ABNORMAL |
| `q3b_cycle_stability` | 주기 안정도가 10 백분위 미만(더 불안정한 쪽만)이면 ABNORMAL |
| `q3c_phase_service` | 평가 대상 접근로 중 하나라도 녹색 비율이 범위 밖이면 ABNORMAL. 이상이 없는데 값이나 이력이 빠진 접근로가 있으면 INSUFFICIENT |
| `q3` | 세 측정값 중 2개 이상 ABNORMAL이면 ABNORMAL, 2개 이상 평가 가능하면 NORMAL, 아니면 INSUFFICIENT |
| `category_without_q2_gate` | Q2를 통과했다고 가정했을 때의 분류. 나머지 규칙(녹색 없음이면 Grey 등)은 그대로 적용 |
| `category` | 실제 스크리닝 분류 |

`abnormal_each_question_alone` / `normal_each_question_alone`: 위 질문별로 ABNORMAL / NORMAL인 교차로 수입니다.

## 3. 겹침과 조합

- **`overlap_of_data_checks`:** 두 데이터 점검에 **동시에** 해당하는 교차로 수입니다(예: `no_current_cycle_length & detector_records_missing`). 한 교차로가 여러 쌍에 들어갈 수 있습니다.
- **`most_common_combinations`:** 교차로마다 해당하는 데이터 문제를 모두 이어 붙인 조합별 교차로 수입니다(상위 15개). **각 교차로는 한 번만** 세므로, 전체 조합을 합치면 교차로 수와 같습니다. `(no data problem)`은 어느 점검에도 해당하지 않는 교차로입니다.

## 4. 읽을 때 주의할 점

- 하나의 교차로가 여러 점검에 동시에 해당하므로, 항목별 개수를 더하면 전체 교차로 수보다 큽니다.
- "기록된 녹색 없음"(`approach_hasgreen_0`)과 "기록 결측"(`approach_no_green_record`)은 다른 것입니다. 앞의 것은 실제로 측정된 0이고, 뒤의 것은 데이터가 없는 것입니다.
- 이 명령은 분석 전용입니다. 스크리닝 분류, 로그, 스냅샷은 바뀌지 않습니다.
