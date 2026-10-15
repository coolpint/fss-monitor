# fss-monitor Plan

## 현재 운영 상태 — 2026-10-15

- 사용자 승인으로 남은6건을 #fss-monitor로 발송하고 정기 운영을 재개했다. FSS_MONITOR_ENABLED=true, monitor/weekly-health-check 모두 active이다.
- 실제 실행 38658260475 성공 및 Slack 6건 개별 수신을 확인했다. Actions 커밋 7151407에 6건 notified와 운영 상태(시도6/성공6/실패0)가 저장됐다. 과거 생략108건과 이전 메타데이터를 보존했다.
- 운영 재개는 기존 인증/목적지/스케줄을 사용하며 새 credential/권한이나 Teams 발송은 없다. 수동 실행은 한 번뿐이다.
- 다음 수집 예약은 10/15 10:00 KST, 주간 점검은 10/16 15:45 KST이다. 첫 주간 점검은 이전 중지 기간도 포함한다.
- 작업/변경/검증 상세와 Slack TS는 docs/operations-resume-2026-10-15.md에 기록했다. 아래 과거 복구/보류 기록은 시점별 이력이다.

2026-10-13 08:12 UTC 복구 검증: 사용자 직접 SLACK_WEBHOOK_URL 등록 완료 후 main 코드 커밋 6db4630 반영 및 시험 run 38367378134의 Slack 실수신(메시지 ts 1791878990.538019) 확인 완료. 최신 수집 후보 113건 중 108건을 skipped_by_user로 적용하고 최신5건은 미전송 유지했다. 원본/준비/적용본과 감사 기록은 recovery-preparation/20261013T081201006097Z/에 보존한다. GitHub가 파일 반영 시 자동 활성화한 정기 두 workflow는 disabled_manually로 다시 중지했고 FSS_MONITOR_ENABLED variable은 미설정이다. 정기 재활성화는 별도 승인 전 보류한다.

2026-10-13 연결 후속 진행: 사용자 승인으로 전용 Slack 앱 A0C8B5ZMQF9 생성 및 Incoming Webhooks 활성화 완료. 새 명시적 약관이 표시된 OAuth 허용 단계와 GitHub 사용자 직접 로그인/secret 입력에서 인계 대기 중이다. 비밀 URL 생성/등록/발송/원격 반영/seen 적용은 아직 하지 않았다. 시험 전용 실행은 수집/후보/상태 저장 없이 알림 1건만 보내도록 준비했다.

## 1. 현재 기획 의도

이 프로젝트는 금융감독원 제재 관련 공시를 놓치지 않고 감지해 Slack으로 알리고, 후속 기사 작성 작업으로 자연스럽게 이어지게 만드는 자동화 프로젝트다.

현재 기준은 명확하다.

1. GitHub Actions 또는 로컬 실행으로 금감원 제재 공시 목록을 주기적으로 확인한다.
2. 새 공시가 있으면 Slack으로 원문 링크를 보낸다.
3. 로컬 `article_pipeline.py`가 해당 공시의 PDF를 다운로드하고 텍스트를 추출한다.
4. 기사 작성, 이미지 생성, moneynlaw 미승인 글 저장은 `/Users/sanghoon/codes/Auto-Writer`에 인계한다.
5. 공개 발행, 승인 완료, 예약 발행, 기존 공개 기사 수정·삭제는 사용자 명시 승인 없이 하지 않는다.

## 2. 현재 프로젝트 상태

- 저장소 위치: `/Users/sanghoon/codes/fss-monitor`
- 핵심 파일:
  - `monitor.py`: 금감원 제재 공시 목록 확인, 신규 공시 감지, Slack 알림, 선택적 PDF 다운로드
  - `article_pipeline.py`: PDF 다운로드, PDF 텍스트 추출, Auto-Writer 입력·작업·상태 파일 생성
  - `weekly_health_check.py`: GitHub Actions 기반 모니터 실행 상태 점검 및 Slack 주간 알림
  - `.github/workflows/monitor.yml`: 매시간 실행
  - `.github/workflows/weekly-health-check.yml`: 매주 금요일 15:45 KST 상태 점검
  - `seen.json`: 이미 처리한 공시 상태
  - `service_config.example.json`: 로컬 설정 예시
- 기본 동작:
  - `ALERT_LINK_ONLY=1`: Slack 링크 알림만 전송
  - `ALERT_LINK_ONLY=0`: PDF 다운로드 후 Slack으로 저장 정보 전송
  - 기본 목록 스캔 범위: 30페이지(`FSS_MAX_LIST_PAGES=30`)
  - 로컬 기사화 산출물: `runs/` 아래 생성, git에는 커밋하지 않음

## 3. 목표 워크플로

1. 금감원 제재 공시 신규 알림을 감지한다.
2. 새 공시 링크를 Slack으로 보낸다.
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

- 알림 채널은 Slack이다.
- 기사 작성과 CMS 저장은 Auto-Writer가 담당한다.
- 금감원 징계해설 기사에는 `auto_writer_source.md`에 포함된 전용 이미지 프롬프트를 적용한다.
- CMS 저장 목표는 `미승인` 또는 안전한 검토 대기 상태다.
- 공개 발행, 승인 완료, 예약 발행은 자동으로 하지 않는다.
- 로그인 정보, 쿠키, 세션, 비밀번호, API 키, Slack 토큰은 저장소에 저장하지 않는다.
- 새 공시 처리 여부는 `seen.json`의 처리 키를 기준으로 판단한다.
- 날짜 high-water mark는 참고용이며, 과거 일자라도 `seen.json`에 없으면 새 공시로 처리한다.

## 5. 설정

GitHub Actions secrets 또는 로컬 환경변수:

- `SLACK_WEBHOOK_URL`: #fss-monitor 전용 Incoming Webhook, 승인된 Actions secret
- `SLACK_CHANNEL_ID`: 확인된 채널 C0C9LQN7A64, workflow에 고정
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

- 신규 공시는 Slack으로 알린다.
- 주간 상태 점검도 Slack으로 보낸다.
- Slack 설정이 없으면 실패로 보고하며 Teams/Telegram으로 fallback하지 않는다.
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

### 2026-10-13 로컬 복구 작업

- 사용자의 복구 시작 승인 범위에서 로컬 수정과 mock 테스트만 수행했다. 원격 push/main 반영, Actions 재활성화, 시험 알림, 누적 공시 재전송은 하지 않았다.
- 알림 시도/성공/실패를 분리하고 수집 실패·빈 목록 파싱·알림 실패를 비정상 종료로 처리했다. 부분 성공한 공시만 기존 seen 상태에 기록한다.
- `monitor_health.json`에 UTC 수집/알림 성공 시각 및 최근 결과를 저장한다. 새 공시가 없는 실행은 기존 알림 성공 시각을 유지한다. 과거의 성공 배지에서 전송 성공 시각을 추정하지 않는다.
- 실패 실행에서도 상태를 저장하고 동일 브랜치 모니터 실행을 직렬화한다. 운영 상태 저장은 매시간 상태 커밋을 만들 수 있다.
- `--dry-run`은 목록/미전송 후보를 출력하며 외부 알림과 상태 저장을 하지 않는다. 손상된 seen 기록을 비우고 계속하는 동작은 중단한다.
- 주간 점검은 현재 workflow cron에서 예상 실행 횟수(7일 168회)를 계산하며 workflow state와 실제 최근 수집 결과를 함께 확인한다. 비정상 점검은 종료코드 1이다.
- 테스트 20개 통과. 현재 공개 목록 278건/미전송 후보 113건을 확인했다. 상세 근거·안전 재가동 순서는 `docs/recovery-2026-10-13.md`에 남겼다.

## 10. 로컬 복구 변경 기록

### 2026-10-13

- 알림 실패를 성공 처리하던 동작과 주간 점검의 일일 예상 횟수 오류를 수정했다.
- 기존 채널 우선순위, 매시간 수집/금요일 점검 스케줄, seen 키와 공시 데이터를 보존했다.
- article_pipeline, Auto-Writer, CMS 코드는 변경하지 않았다.
- Teams HTTP 500의 내부 원인은 응답 본문 부재로 확정하지 못했다. 목적지 변경이나 비밀값 조회/출력은 하지 않았다.

### 2026-05-18

- 현재 기준과 혼동되는 과거 직접 브라우저 조작 중심 설명을 제거했다.
- 현재 운영 모델을 Telegram 알림 + Auto-Writer 인계로 단순화했다.

### 2026-05-23

- 알림 운영 모델을 Telegram 우선 + Teams fallback으로 보강했다.
- 주간 헬스체크의 오래된 queued run false positive를 제거했다.


### 2026-10-13 Slack 전환 추가 작업/결정

- 사용자 지시에 따라 monitor와 주간 점검을 Slack 전용 발송으로 수정했다. Teams/Telegram 발송 함수와 Actions secret 주입을 제거했다. 과거 변경 기록은 역사 기록으로 유지한다.
- 저장소 secret 이름만 읽은 결과 TEAMS_WEBHOOK_URL 하나, Actions variable은 없음. Slack 기존 연결은 확인되지 않았다. 비밀값은 조회/출력하지 않았다.
- 부모의 Slack 채널 생성이 사용자 취소되어 채널이 없는 상태다. 이 작업에서는 생성/시험 발송을 시도하지 않는다.
- Slack bot API는 chat:write 권한과 확인된 채널 ID를 사용하는 구현 준비이며 새 token/OAuth/webhook 생성 또는 secret 등록은 미실행이다.
- 최신 후보를 재수집해 최신 5건을 미전송으로 남기고 나머지를 skipped_by_user로 기록하는 준비 파일과 원본 백업을 생성했다. 실제 seen 상태 변경은 Slack Actions 연결 검증 이후에만 수행한다.
- 실제 전송 성공(notified)과 사용자 지시에 따른 알림 생략(skipped_by_user)을 구분한다. 준비 파일은 applied=false이며 seen은 변경하지 않는다.
- mock 테스트 26개 통과. 원격 push/main/재활성화/실제 알림/seen 변경은 미실행이다.

- 후속 확인: 부모가 사용자 재시도 승인 후 Silverlining Solutions(T054M7CUG)의 #fss-monitor(C0C9LQN7A64)를 생성했다. 대상 ID를 로컬 코드/workflow에 고정하며 다른 채널을 지정하면 발송을 거부한다. 커넥터 시험 메시지와 Actions 연결 검증은 별개이다.


### 2026-10-13 최소 권한 재검토

- 단일 채널에 공시 링크/주간 점검 텍스트만 전송하므로 bot token/chat:write가 필수는 아니다. 공식 Slack 문서를 확인해 채널 고정 Incoming Webhook 방식으로 로컬 코드를 전환했다. 이전 bot token 연결안은 대체되었다.
- 필요한 secret은 SLACK_WEBHOOK_URL 한 개다. 확인된 workspace URL만 허용하며 HTTP 200 + 본문 ok를 성공으로 처리한다. redirect/다른 host/다른 workspace/오류 응답은 실패하고 비밀 본문은 출력하지 않는다.
- webhook 생성 시 #fss-monitor(C0C9LQN7A64)를 선택해야 한다. URL에서 채널 ID를 알아낼 수 없으므로 사용자 설치 화면과 승인된 실제 수신 검증이 필요하다.
- Incoming Webhook/OAuth/설치/secret 등록/시험 발송은 하지 않았다. 테스트 27개 통과, 실제 seen은 보존했다.
