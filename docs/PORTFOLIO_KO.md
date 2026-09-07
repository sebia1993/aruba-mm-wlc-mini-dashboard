# Aruba 클러스터 상태 판단: 코드로 확인하는 운영 설계

이 프로젝트의 검토 포인트는 여러 CLI 출력을 장비 IP에 연결하고, 수집 신뢰도와 연속 관측을 고려해 운영 상태를 표시하는 과정입니다. [README 화면](../README.md#실행-화면)은 비식별 fixture로 렌더링한 실제 UI이며 운영 현장 실적을 나타내지 않습니다.

## 사례: Client 수가 갑자기 낮아졌을 때

한 Controller의 Active Client가 0이어도 곧바로 고장을 확정하지 않습니다. 정상 수집 여부, Cluster 전체 사용량, 다른 구성원의 값과 연속 이상 횟수를 함께 봅니다. 전체가 저사용량이면 특정 구성원 장애 판정을 보류하고, MM이 명시적으로 Down을 보고하면 별도의 직접 증거로 처리합니다.

| 운영 판단 | 구현 경로 | 합성 검증 근거 |
|---|---|---|
| 한 번 낮아진 값과 지속 이상 분리 | [anomaly_detector.py](../src/aruba_mini_dashboard/services/anomaly_detector.py) | [test_anomaly_detector.py](../tests/test_anomaly_detector.py): 1회 보류, 3회 이상, 2회 복구 |
| 전체 저사용량과 특정 구성원 이상 구분 | 같은 detector의 전체값·Peer 조건 | 같은 테스트의 `test_all_low_cluster_skips_specific_member_judgment` |
| SSH·파싱 실패를 Down으로 해석하지 않음 | [correlation_engine.py](../src/aruba_mini_dashboard/services/correlation_engine.py), [collectors](../src/aruba_mini_dashboard/collectors/) | [correlation tests](../tests/test_correlation_engine.py), [collector tests](../tests/test_infra_collectors.py) |
| 확인 처리와 실제 복구를 분리 | [incident_manager.py](../src/aruba_mini_dashboard/services/incident_manager.py) | [incident tests](../tests/test_incident_manager.py) |
| Connection-Type 변화의 기준 보존 | [connection_types.py](../src/aruba_mini_dashboard/connection_types.py), [baseline 설계](DETECTION_LOGIC_KO.md) | [baseline acceptance tests](../tests/test_connection_baseline_acceptance_contract.py) |
| 많은 장비 행에서도 표시 책임 분리 | [UI models](../src/aruba_mini_dashboard/ui/models/), [합성 benchmark](../scripts/benchmark_device_models.py) | [device model tests](../tests/test_device_table_model.py), [performance report](PERFORMANCE_REPORT_KO.md) |

데이터 흐름과 경계는 [ARCHITECTURE_KO.md](ARCHITECTURE_KO.md), 변경 명령이 있는 별도 기능은 [AUTOMATIC_REMEDIATION_KO.md](AUTOMATIC_REMEDIATION_KO.md)에서 검토합니다. 자동 장애조치는 기본 OFF이며 읽기 전용 수집과 다른 권한·감사 경계를 갖습니다.

## 장비 없이 재현하기

Windows x64·CPython 3.13.15에서 저장소 루트의 개발 환경을 준비합니다. 고정 의존성 설치에는 개발 환경 네트워크가 필요하지만 Demo와 아래 fixture 검증에 장비 계정은 필요하지 않습니다.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pytest -q tests/test_anomaly_detector.py tests/test_correlation_engine.py tests/test_incident_manager.py tests/test_evidence_boundaries.py
.\scripts\run_demo.ps1
```

Demo는 [demo.py](../src/aruba_mini_dashboard/demo.py)의 fixture 공급 경로를 사용합니다. 정상 → Client 저하 → Connection-Type 변화 → MM Down → 복구 흐름에서 표시 상태와 근거를 살펴보십시오. 실행 ZIP에서도 `ArubaMiniDashboard.exe --demo`를 사용할 수 있습니다.

화면 모델의 합성 부하는 다음처럼 별도로 재현합니다.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe scripts/benchmark_device_models.py --sizes 250 1000 5000 --repeat 3
```

이는 메모리 내 장비 행의 로딩·정렬·필터 시간입니다. 5,000대 SSH 동시 수집 능력, 네트워크 지연, 운영망 성능 또는 현장 규모의 증거가 아닙니다. 하드웨어·OS·실행 조건을 함께 기록해야 비교할 수 있습니다.

## 검증과 남은 한계

[Windows CI](../.github/workflows/ci-windows.yml)는 기존 [package_release.ps1](../scripts/package_release.ps1) 경로로 테스트·패키지·추출 EXE를 검증합니다. [run_tests.ps1](../scripts/run_tests.ps1)은 전체 pytest 후 1,000회 결정적 fault-injection 반복을 실행합니다. 위의 짧은 fixture 명령을 전체 CI·soak 통과로 표현하지 않습니다.

- 실제 Aruba MM/7240XM, 실제 Windows 11 PC, 드라이버·회사 보안 정책은 [현장 체크리스트](WINDOWS11_QA_CHECKLIST_KO.md)의 별도 증거가 필요합니다.
- 기본 임계값은 판단 정책이며 환경에 무관한 장애 기준이 아닙니다. 운영 기준과 예상 부하를 검토해야 합니다.
- 자동 장애조치의 fixture 성공을 실제 재부팅·재분배 성공이나 운영 사용 승인으로 해석하지 않습니다.
- 포트폴리오에서 제시하는 근거는 상태 모델·오탐 억제 조건·테스트·배포 절차입니다. MTTR 감소나 장애 예방 건수는 측정된 현장 자료가 있을 때만 추가합니다.
