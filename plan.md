# fss-monitor Plan

## 1. 현재 기획 의도

이 프로젝트는 금융감독원 제재 관련 공시를 놓치지 않고 감지해 Telegram으로 알리고, 후속 기사 작성 작업으로 자연스럽게 이어지게 만드는 자동화 프로젝트다.

현재 기준은 명확하다.

1. GitHub Actions 또는 로컬 실행으로 금감원 제재 공시 목록을 주기적으로 확인한다.
2. 새 공시가 있으면 Telegram으로 원문 링크를 보낸다.
3. 로컬 `article_pipeline.py`가 해당 공시의 PDF를 다운로드하고 텍스트를 추출한다.
4. 기사 작성, 이미지 생성, moneynlaw 미승인 글 저장은 `/Users/sanghoon/codes/Auto-Writer`에 인계한다.
5. 공개 발행, 승인 완료, 예약 발행, 기존 공개 기사 수정·삭제는 사용자 명시 승인 없이 하지 않는다.

## 2. 현재 프로젝트 상태

- 저장소 위치: `/Users/sanghoon/codes/fss-monitor`
- 핵심 파일:
  - `monitor.py`: 금감원 제재 공시 목록 확인, 신규 공시 감지, Telegram 알림, 선택적 PDF 다운로드
  - `article_pipeline.py`: PDF 다운로드, PDF 텍스트 추출, Auto-Writer 입력·작업·상태 파일 생성
  - `weekly_health_check.py`: GitHub Actions 기반 모니터 실행 상태 점검 및 Telegram 주간 알림
  - `.github/workflows/monitor.yml`: 매시간 실행
  - `.github/workflows/weekly-health-check.yml`: 매주 금요일 15:45 KST 상태 점검
  - `seen.json`: 이미 처리한 공시 상태
  - `service_config.example.json`: 로컬 설정 예시
- 기본 동작:
  - `ALERT_LINK_ONLY=1`: Telegram 링크 알림만 전송
  - `ALERT_LINK_ONLY=0`: PDF 다운로드 후 Telegram으로 저장 정보 전송
  - 기본 목록 스캔 범위: 30페이지(`FSS_MAX_LIST_PAGES=30`)
  - 로컬 기사화 산출물: `runs/` 아래 생성, git에는 커밋하지 않음

## 3. 목표 워크플로

1. 금감원 제재 공시 신규 알림을 감지한다.
2. 새 공시 링크를 Telegram으로 보낸다.
3. 로컬 파이프라인에서 상세 페이지의 PDF를 다운로드한다.
4. PDF 텍스트를 추출한다.
5. 작업 폴더에 다음 파일을 만든다.
   - `metadata.json`
   - `pdf/`
   - `pdf_text.txt`
   - `auto_writer_source.md`
   - `auto_writer_task.md`
   - `auto_writer_state.json`
   - `handoff.md`
   - `status.json`
6. Auto-Writer가 `auto_writer_source.md`를 기반으로 기사 작성, 이미지 생성, CMS 미승인 저장을 수행한다.
7. 완료 결과는 `auto_writer_state.json`에 기록한다.

## 4. 운영 원칙

- 알림 채널은 Telegram이다.
- 기사 작성과 CMS 저장은 Auto-Writer가 담당한다.
- 금감원 징계해설 기사에는 `auto_writer_source.md`에 포함된 전용 이미지 프롬프트를 적용한다.
- CMS 저장 목표는 `미승인` 또는 안전한 검토 대기 상태다.
- 공개 발행, 승인 완료, 예약 발행은 자동으로 하지 않는다.
- 로그인 정보, 쿠키, 세션, 비밀번호, API 키, Telegram 토큰은 저장소에 저장하지 않는다.
- 새 공시 처리 여부는 `seen.json`의 처리 키를 기준으로 판단한다.
- 날짜 high-water mark는 참고용이며, 과거 일자라도 `seen.json`에 없으면 새 공시로 처리한다.

## 5. 설정

GitHub Actions secrets 또는 로컬 환경변수:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TEAMS_WEBHOOK_URL` 선택값. Telegram 설정이 없을 때 기존 Teams Webhook fallback으로 사용한다.
- `FSS_MAX_LIST_PAGES` 선택값
- `AUTO_WRITER_PROJECT_DIR` 선택값, 기본 `/Users/sanghoon/codes/Auto-Writer`
- `AUTO_WRITER_MODE` 선택값, 기본 `live`
- `AUTO_WRITER_CHANNEL` 선택값, 기본 `fss-monitor`
- `MONEYNLAW_LOGIN_URL` 선택값
- `MONEYNLAW_WRITE_URL` 선택값
- `MONEYNLAW_REVIEW_STATUS` 선택값, 기본 `미승인`

## 6. 단계별 계획

### Phase 1. 모니터 안정화

- 금감원 목록을 기본 30페이지까지 확인한다.
- 새 공시는 공시일과 상관없이 `seen.json`에 없으면 알림한다.
- 알림 실패 시 `seen.json`에 기록하지 않고 다음 실행에서 재시도한다.

### Phase 2. 알림 운영

- 신규 공시는 Telegram으로 알린다.
- 주간 상태 점검도 Telegram으로 보낸다.
- Telegram secrets가 준비되지 않은 환경에서는 기존 `TEAMS_WEBHOOK_URL`로 fallback한다.
- 알림 설정 누락 때문에 모니터가 조용히 무력화되지 않도록 테스트와 헬스체크를 유지한다.

### Phase 3. Auto-Writer 인계

- `article_pipeline.py`는 PDF 다운로드와 텍스트 추출까지만 직접 처리한다.
- 이후 단계는 Auto-Writer에 넘긴다.
- Auto-Writer 인계 파일은 `auto_writer_*`로 통일한다.

### Phase 4. 기준선 관리

- 오늘 테스트에 사용한 공시는 처리 완료 기준선에 포함한다.
- 이후에는 그 뒤로 올라오는 공시만 신규 대상으로 삼는다.
- 다만 이전 공시를 강제로 재처리할 때는 `article_pipeline.py --item-url ... --force --no-state`처럼 명시적으로 실행한다.

## 7. 결정 기록

### 2026-05-18

- 결정: 신규 공시와 주간 점검 알림 채널은 Telegram으로 한다.
- 결정: 알림 전송 경로는 Telegram Bot으로 단일화한다.
- 결정: PDF 다운로드 이후 기사 작성, 이미지 생성, CMS 저장은 Auto-Writer로 인계한다.
- 결정: 후속 기사화 인계 방식은 Auto-Writer 작업 파일로 단일화한다.
- 결정: moneynlaw 저장 목표는 공개 발행이 아니라 미승인/검토 대기 글 저장이다.
- 결정: 금감원 징계해설 기사에는 별도 이미지 프롬프트를 적용한다.
- 결정: 오늘 확인한 새 공시는 테스트 처리 후 기준선에 포함하고, 이후 올라오는 공시를 신규 대상으로 삼는다.

### 2026-05-23

- 결정: Telegram을 우선 알림 채널로 유지하되, 현재 저장소 secrets에는 `TEAMS_WEBHOOK_URL`만 있으므로 Telegram secrets가 없으면 Teams Webhook으로 fallback한다.
- 결정: 주간 헬스체크에서 오래된 queued run은 이후 성공 실행이 있으면 장애로 보지 않는다.

## 8. 작업 기록

### 2026-05-18

- `monitor.py` 알림 경로를 Telegram Bot 메시지 전송으로 변경했다.
- `.github/workflows/monitor.yml`과 `.github/workflows/weekly-health-check.yml`이 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` secrets를 사용하도록 변경했다.
- `weekly_health_check.py`의 점검 로직과 금요일 15:45 KST 스케줄은 유지하고 결과 전송만 Telegram으로 변경했다.
- `article_pipeline.py`가 PDF 다운로드와 텍스트 추출 뒤 `auto_writer_source.md`, `auto_writer_task.md`, `auto_writer_state.json`을 생성하도록 바꿨다.
- `service_config.example.json`, README, constitution, agent 문서를 Telegram/Auto-Writer/미승인 저장 기준에 맞게 갱신했다.
- 회귀 방지 테스트를 Telegram/Auto-Writer 흐름 기준으로 갱신했다.
- 현재 기준과 혼동되는 과거 직접 브라우저 조작·외부 생성 도구·이전 알림 채널 설명을 문서와 코드에서 제거했다.
- 실제 금감원 목록에서 신규로 남아 있던 최신 공시 `국민은행 제재관련 공시`(`id:202500229_1`, 공시일 2026.05.12)를 확인했다.
- 해당 공시 PDF를 다운로드하고 `runs/20260512_202500229_1_국민은행-제재관련-공시/`에 Auto-Writer 인계 패키지를 생성했다. 상태는 `auto_writer_ready`, CMS 검토 상태는 `미승인`이다.
- 현재 목록 147건을 기준선으로 저장했다. 이번에 기준선에 새로 포함된 키는 `id:202500229_1`, `id:202500806_1`, `id:202500121_1`이며, 이후 올라오는 공시만 신규 대상으로 삼는다.

### 2026-05-23

- 주간 헬스체크 실패를 조사했다. 실제 모니터 scheduled run은 계속 성공 중이었고, 실패 원인은 Telegram secrets 부재와 오래된 queued run 판정이었다.
- `monitor.py`와 `weekly_health_check.py`가 Telegram secrets 부재 시 기존 `TEAMS_WEBHOOK_URL`로 fallback하도록 수정했다.
- `weekly_health_check.py`는 오래된 queued run 뒤에 성공 실행이 있으면 해당 queued run을 헬스체크 실패 원인으로 보지 않도록 바꿨다.
- 로컬 검증 결과, 현재 주간 헬스체크 요약은 `healthy=true`, 실패 0건, 미완료 0건으로 계산된다.

## 9. 변경 기록

### 2026-05-18

- 현재 기준과 혼동되는 과거 직접 브라우저 조작 중심 설명을 제거했다.
- 현재 운영 모델을 Telegram 알림 + Auto-Writer 인계로 단순화했다.

### 2026-05-23

- 알림 운영 모델을 Telegram 우선 + Teams fallback으로 보강했다.
- 주간 헬스체크의 오래된 queued run false positive를 제거했다.
