# Slack 전환 준비 및 남은 승인

## 현재 검증 완료 상태 (2026-10-13 08:12 UTC 이후)

- 사용자가 직접 Slack 설치와 GitHub secret 등록을 완료했다. `SLACK_WEBHOOK_URL` 이름/수정일만 읽어 등록을 확인했고 비밀값은 읽거나 출력하지 않았다.
- 복구 코드 커밋 `6db4630`을 승인된 main에 반영했다.
- 시험 전용 Actions [38367378134](https://github.com/coolpint/fss-monitor/actions/runs/38367378134)이 성공했다. 생성 08:09:39 UTC, 발송 08:09:50 UTC (17:09:50 KST). 실제 #fss-monitor 메시지 ts `1791878990.538019`를 Slack 읽기 도구로 확인했다. 문구: `[fss-monitor 연결 확인 run 38367378134] GitHub Actions → #fss-monitor 시험 알림입니다. 과거 공시는 발송하지 않았습니다.`
- 정기 재활성화는 하지 않는다. GitHub가 workflow 파일 반영 직후 기존 두 workflow를 자동 active로 바꿔 다시 disabled_manually로 중지했다. 모든 정기 실행에는 `FSS_MONITOR_ENABLED == 'true'` job 조건이 있으며 해당 Actions variable은 없다. 실제 최근 실행 목록에는 시험 1건 외 추가 실행이 없다.
- 수신 확인 뒤 공개 목록을 새로 수집했다. 목록 278 / 후보 113 / 생략 108 / 미전송 유지 5건이며 최신5 목록은 아래 표와 동일했다.
- 적용 감사/백업 디렉터리: `recovery-preparation/20261013T081201006097Z/`. 이전 seen 키 165개와 기존 메타데이터를 보존하고 사용자 생략 108개를 추가해 273개가 되었다. 생략 status는 `skipped_by_user`이며 실제 알림 성공으로 표시하지 않는다. 감사 파일에는 applied=true 및 시험 run/채널/메시지 ts, 원본·적용 SHA256을 남겼다. 알림은 시험 1건만 발송했다.
- 저장소 state 반영은 별도 승인된 후속 커밋으로 진행한다. `--test-alert-only`는 상태/수집을 건드리지 않는다. 로컬 테스트 28개 통과.

운영 재개에 필요한 별도 승인 후 단계: 먼저 최신 pending과 정상 Slack 연결을 확인한 뒤 Actions variable `FSS_MONITOR_ENABLED`를 `true`로 설정하고 monitor.yml 및 weekly-health-check.yml을 enable한다. 기존 미전송 5건과 이후 새 후보는 정상 monitor 실행에서 전송 대상이다. 정기 재개 이전에는 variable과 enable을 수행하지 않는다.

## 연결 승인 후 진행 상태

- 사용자 승인을 받아 Silverlining Solutions에 빈 전용 앱 `fss-monitor` (`A0C8B5ZMQF9`)를 생성하고 Incoming Webhooks를 활성화했다.
- 설치 요청 scope는 `incoming-webhook`만이다. OAuth 화면에서 #fss-monitor를 선택했으나 Slack이 허용 시 앱 개인정보 보호 계약/서비스 약관에도 동의한다고 명시해 `허용`을 누르지 않았다. 사용자 지시의 새 명시적 약관 보고 조건에 따라 중단했다. webhook URL은 아직 생성하지 않았다.
- Slack 승인 탭(2132631813)을 인계용으로 유지했다. 설정 링크: https://api.slack.com/apps/A0C8B5ZMQF9/incoming-webhooks
- GitHub 브라우저는 로그아웃 상태다. New repository secret 페이지로 이어지는 로그인 탭(2132631816)을 인계용으로 유지했다. 로그인 후 사용자가 SLACK_WEBHOOK_URL이라는 이름으로 직접 복사/입력/제출해야 한다. 에이전트가 비밀값을 읽거나 대신 입력하지 않는다.
- 원격 반영과 시험 알림 1건은 승인되었으나 secret 입력/등록 확인 전에는 미실행이다. 정기 Actions 재활성화는 계속 보류한다.
- `--test-alert-only` 및 workflow_dispatch 기본 test_only=true를 추가해 시험 1건이 공시 수집/후보 알림/상태 저장으로 이어지지 않게 했다. mock 테스트 28개 통과.

## 현재 결과

- Silverlining Solutions / cooltaku (`T054M7CUG`)의 [#fss-monitor](https://cooltaku.slack.com/archives/C0C9LQN7A64), 채널 ID `C0C9LQN7A64`를 부모가 생성·조회했다.
- 로컬 monitor와 주간 점검을 Slack 전용으로 전환했다. Teams/Telegram 함수와 workflow secret 주입을 제거했다. 원격 코드는 아직 변경되지 않았다.
- `slack_notifications.py`는 확인된 채널 설정과 workspace URL 형식을 검사하며 Incoming Webhook HTTP 200 + 본문 ok를 성공 조건으로 요구한다. 오류 응답 본문과 token은 출력하지 않는다. 애매한 연결 실패에는 자동 재시도하지 않는다.
- GitHub Actions의 repo secret 이름/수정일만 읽었다. 등록 이름은 `TEAMS_WEBHOOK_URL` 하나이고 Actions variable은 없다. 새 Slack credential 생성/읽기/등록을 하지 않았다.
- 부모 보고: 커넥터 시험 게시물은 자동 승인 검토가 구체 승인 부족으로 거부했다. 실제 게시되지 않았다. 이 작업에서는 우회 또는 시험 발송을 시도하지 않았다.
- 모의 테스트 27개 통과. 실제 GitHub Actions → Slack 발송 경로는 미검증이다.

## 승인 후 필요한 최소 권한 연결 단계

현재 로컬 구현은 Incoming Webhook 전용이다. 이전 bot token/chat:write 제안은 이 방식으로 대체되었다. 현재 기능은 단일 채널에 텍스트를 게시하며 메시지 수정/삭제, 파일 업로드, 스레드 응답, 채널 읽기 기능이 없어 bot credential이 필수인 이유가 없다.

1. 사용자가 승인하면 이 workspace의 Slack app에 Incoming Webhooks를 활성화하고 `Add New Webhook to Workspace`에서 #fss-monitor(C0C9LQN7A64)를 선택해 승인한다. 적합한 app이 없으면 webhook 전용 app 생성/설치 승인도 필요하다. 요청할 권한은 `incoming-webhook`이다. chat:write, chat:write.public, 채널 기록 읽기 권한은 요청하지 않는다.
2. 생성된 URL은 비밀값이다. 사용자가 직접 GitHub coolpint/fss-monitor → Settings → Secrets and variables → Actions → New repository secret에서 이름 `SLACK_WEBHOOK_URL`로 입력한다. 이 지속 접근 등록 역시 구체 승인 대상이다. URL을 대화·코드·로그로 보내거나 에이전트가 값을 읽는 절차는 필요하지 않다.
3. 공식 Slack Incoming Webhook은 생성 시 선택한 채널에 고정되고 요청에서 channel을 바꿀 수 없다. payload에도 channel override를 넣지 않는다. 코드가 확인된 workspace의 hooks.slack.com URL 형식과 로컬 channel 설정을 검사하지만 URL만으로 실제 채널 ID를 확인할 수는 없다.
4. 따라서 생성 화면의 채널 확인과 승인된 GitHub Actions 시험 알림 1건의 #fss-monitor 실제 수신 확인이 필요하다. connector 시험과 Actions webhook 경로 검증은 별개다. 시험에는 과거 후보를 넣지 않고 URL/응답 비밀값을 로그에 남기지 않는다. 시험/원격 branch 반영은 아직 승인되지 않았다.
5. webhook 정상 응답은 HTTP 200과 plain text ok다. 메시지 ts는 반환하지 않으므로 이전 bot API의 ts/channel 검증은 제거했다. HTTP 실패/예상하지 않은 200 본문/redirect/연결 오류는 실패로 처리하고 자동 재시도하지 않는다. HTTP 응답은 Slack의 수락 증거이며 목적지 실제 수신 검증은 별도로 남긴다.
6. Actions 연결 검증 후에만 준비된 상태를 적용한다. 적용 전 seen 원본 SHA256과 최신 목록을 재확인한다. 상태 변경을 검증한 뒤 승인 범위에 따라 원격 반영/재활성화를 진행한다.

공식 근거: [Slack Incoming Webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/). 단일 채널 전송에 필요한 권한 범위를 줄일 수 있다는 판단은 문서의 채널 고정 특성과 현재 코드 기능을 비교한 결과다.

## 최신 후보 처리 준비

- 실시간 재수집 결과: 목록 278건, 후보 113건. 생략 준비 108건 / 미전송 유지 5건.
- 준비 디렉터리: `recovery-preparation/20261013T073603551507Z/`.
- `seen.original.json`: 변경 전 byte 단위 백업. `seen.prepared.json`: 적용 후보, 아직 사용하지 않음. `audit.json`: SHA256/전체 생략 및 유지 목록/정렬 기준/미적용 표시. `collected.json`: 공개 목록 snapshot.
- 기존 seen을 변경하지 않았다. 기존 실제 성공 status `notified`는 그대로 보존하고, 생략 후보는 `skipped_by_user` status로 구분한다. 생략은 실제 전달 성공을 의미하지 않는다. 최신 공시 날짜 high-water 값도 임의 상승시키지 않는다.
- 순서는 공시일 내림차순, 동률은 수집 목록 순서, 그 다음 공시 식별자이다. 원문에서 공시 게시 시각은 제공되지 않으므로 시간을 만들어내지 않는다. monitor 수집 목록의 동률 순서 자체는 공시 ID 내림차순으로 결정되어 반복 수집 시 일관된다.

| 순위 | 공시일 | 제목 | 공시 ID |
|---|---|---|---|
| 1 | 2026.10.01 | 한국투자증권 제재관련 공시 | 202500052_1 |
| 2 | 2026.09.30 | 경성투자자문(주) 제재관련 공시 | 202500019_2 |
| 3 | 2026.09.30 | 신라자산운용 주식회사 제재관련 공시 | 202500018_1 |
| 4 | 2026.09.25 | 한국산업은행 제재관련 공시 | 202200259_1 |
| 5 | 2026.09.23 | 안산농협 제재관련 공시 | 202500503_2 |

## 검토 기록

- Constitution: 사용자가 채널 변경과 과거 생략 정책을 명시하여 로컬 준비가 승인 범위에 속한다. 추가 credential 생성/지속 등록은 승인 전 보류한다.
- Review: 기존 수집 일정/부분 성공 보존/실패 종료를 유지했고, Teams 발송 코드를 제거했다. Auto-Writer/CMS 변경 없음. 준비 상태는 실제 적용과 분리되어 있다.
- Plan/README/constitution 현재 기준을 Slack 정책으로 업데이트했다. 과거 기록은 역사 기록으로 남겼다.
- 테스트는 HTTP 200 오류 본문/설정 불일치/다른 workspace·host·URL/429/연결 오류/인증 부재/전송 비밀 미노출/주간 실패/후보 5건 보존/동률 순서를 포함한다. 모든 외부 발송은 mock이었다.
- 남은 한계: Slack credential과 실제 Actions 송수신이 미검증이다. seen 적용 전 최신 목록이 달라지면 준비본을 새로 만들어야 한다. 운영 재실행은 Slack 연결 및 상태 적용 승인 이후에만 수행한다.
