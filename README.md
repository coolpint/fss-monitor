# 금감원 징계공시 모니터링

금감원 징계공시에 새 글이 올라오면:
1. 신규 공시를 감지하고
2. Teams 채널로 링크 알림을 보냅니다.

## 핵심 변경사항

- 신규 공시 파싱 로직 강화 (누락 방지)
- 기본 확인 시간: 매일 `09:00`, `16:00`
- 실행 모드
  - 1회 실행: `python monitor.py`
  - 스케줄 상시 실행: `python monitor.py --daemon`
- Teams 전송 기본값: Incoming Webhook 링크 알림
- 선택 기능: `ALERT_LINK_ONLY=0` 설정 시 PDF 다운로드/전송 모드 사용

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

```bash
python monitor.py
python monitor.py --daemon
python monitor.py --check-times 09:00,16:00 --daemon
python monitor.py --test
python monitor.py --reset
```

## Teams 설정

### 1) Webhook만 사용하는 경우 (기존 방식)

- `monitor.py`의 `DEFAULT_WEBHOOK_URL` 또는 환경변수 `TEAMS_WEBHOOK_URL` 설정
- 이 경우 파일 업로드는 불가능하고, 알림 카드만 전송됩니다.

### 2) PDF까지 보내려면 (선택)

기본값은 링크 알림 전용입니다.  
PDF 다운로드/전송까지 하려면 먼저 `ALERT_LINK_ONLY=0`으로 설정하고, 아래 환경변수를 설정하세요.

- `TEAMS_TENANT_ID`
- `TEAMS_CLIENT_ID`
- `TEAMS_CLIENT_SECRET`
- `TEAMS_TEAM_ID`
- `TEAMS_CHANNEL_ID`

Graph 모드에서는 PDF를 채널 파일 폴더에 업로드한 뒤, 채널 메시지에 파일 링크를 함께 보냅니다.

## 자동 실행 방법

### 방법 A: 스크립트를 상시 실행

```bash
python monitor.py --daemon
```

### 방법 B: 작업 스케줄러(권장)

작업 스케줄러에 같은 명령을 2개 트리거로 등록:
- 매일 09:00
- 매일 16:00

실행 명령:
```bash
python monitor.py
```

### 방법 C: GitHub Actions로 실행

- `.github/workflows/monitor.yml` 기준으로 매일 `09:00`, `16:00`(KST)에 실행됩니다.
- GitHub Actions는 **원격 저장소(`origin/main`)의 코드**를 실행하므로, 로컬 수정 후 반드시 `git push`까지 해야 반영됩니다.
- GitHub 리포지토리 `Settings > Secrets and variables > Actions`에 `TEAMS_WEBHOOK_URL`을 등록하세요.

### 방법 D: 주간 상태 점검

- `.github/workflows/weekly-health-check.yml` 기준으로 매주 금요일 `15:45`(KST)에 실행됩니다.
- 최근 7일간 `monitor.yml` scheduled 실행 이력을 점검하고, 이상이 없어도 Teams로 `정상 작동 중` 메시지를 보냅니다.
- 점검 기간은 실제 워크플로 시작 시각이 아니라 주간 점검의 예정 시각(`금요일 15:45 KST`)에 고정해 계산하므로, GitHub Actions 지연 때문에 같은 날 `16:00 KST` 실행이 아직 안 잡힌 경우를 누락으로 오판하지 않습니다.
- 실패, 실행 누락, 미완료 run이 있으면 Teams에 `점검 필요` 상태로 요약을 보냅니다.

## 주의

- `--reset` 실행 시 기존 기록(`seen.json`)이 초기화되어 이미 있던 공시도 다시 신규로 처리됩니다.
- 첫 실행은 현재 공시 목록을 기준선으로 저장하고 알림을 보내지 않습니다(다음 실행부터 신규만 알림).
- 처음 설정 후에는 `python monitor.py --test`로 연결/설정을 먼저 확인하세요.
