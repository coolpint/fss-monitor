# 금감원 징계공시 모니터링

금감원 제재 관련 공시에 새 글이 올라오면:

1. 신규 공시를 감지합니다.
2. Telegram으로 링크 알림을 보냅니다.
3. 로컬 기사화 파이프라인에서 PDF를 다운로드하고 Auto-Writer로 후속 기사 작성·이미지 생성·moneynlaw 미승인 글 저장 작업을 넘깁니다.

## 핵심 변경사항

- 신규 공시 파싱 로직 강화(누락 방지)
- GitHub Actions 확인 주기: 매시간
- 기본 로컬 확인 시간: `02:00`
- 기본 목록 스캔 범위: 최근 30페이지(`FSS_MAX_LIST_PAGES=30`)
- 알림 채널: Telegram
- 선택 기능: `ALERT_LINK_ONLY=0` 설정 시 PDF 다운로드 후 Telegram으로 저장 정보를 알림
- PDF 다운로드 이후 기사화 단계: `article_pipeline.py`가 Auto-Writer 입력·실행 인계 파일을 생성
- 금감원 징계해설 기사에만 별도 만평 이미지 프롬프트를 적용
- 주간 점검은 기존처럼 매주 금요일 15:45 KST에 실행하되 결과를 Telegram으로 전송

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

```bash
python monitor.py
python monitor.py --daemon
python monitor.py --check-times 02:00 --daemon
python monitor.py --test
python monitor.py --reset
```

## 알림 설정

GitHub Actions 또는 로컬 환경변수에 아래 값을 설정합니다. 실제 토큰, 채팅 ID, 웹훅은 저장소에 기록하지 않습니다.

기본 우선순위는 Telegram이고, Telegram 설정이 없으면 기존 Teams Webhook으로 대체합니다.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TEAMS_WEBHOOK_URL`

GitHub Actions에서는 `Settings > Secrets and variables > Actions`에 같은 이름의 secrets로 등록합니다.

## 로컬 기사화 파이프라인

Telegram 링크 알림 이후의 후속 작업(PDF 다운로드, PDF 텍스트 추출, Auto-Writer 입력 파일 생성, Auto-Writer 실행 인계)은 로컬 Mac에서 `article_pipeline.py`로 실행합니다.

```bash
python article_pipeline.py --latest
python article_pipeline.py --process-new --max-items 3
python article_pipeline.py --item-url "https://www.fss.or.kr/..."
python article_pipeline.py --daemon
```

생성물은 기본적으로 `runs/` 아래 작업 폴더에 저장됩니다.

- `metadata.json`: 공시 메타데이터
- `pdf/`: 다운로드한 금감원 PDF
- `pdf_text.txt`: PDF 추출 텍스트
- `auto_writer_source.md`: Auto-Writer에 넘길 기사 원문·PDF 추출문·전용 이미지 프롬프트
- `auto_writer_task.md`: Auto-Writer 실행 인계서
- `auto_writer_state.json`: Auto-Writer 실행 단계와 CMS 저장 결과 기록
- `handoff.md`: 다음 작업 순서
- `status.json`: 작업 상태와 확인 필요 항목

로컬 설정이 필요하면 `service_config.example.json`을 참고해 `service_config.local.json`을 만들거나 환경변수를 사용하세요.

- `AUTO_WRITER_PROJECT_DIR`: Auto-Writer 프로젝트 경로. 기본값은 `/Users/sanghoon/codes/Auto-Writer`
- `AUTO_WRITER_MODE`: Auto-Writer 실행 모드. 기본값은 `live`
- `AUTO_WRITER_CHANNEL`: Auto-Writer 작업 채널/분류. 기본값은 `fss-monitor`
- `MONEYNLAW_LOGIN_URL`: moneynlaw.co.kr 회원 로그인 URL
- `MONEYNLAW_WRITE_URL`: moneynlaw.co.kr 기사 작성 URL
- `MONEYNLAW_REVIEW_STATUS`: 기사 작성 화면의 검토 상태. 기본값은 `미승인`
- `FSS_MAX_AUTO_WRITER_INPUT_CHARS`: PDF 추출 텍스트 입력 길이 제한

주의:

- 로그인 정보, 쿠키, API 키, 웹훅, Telegram 토큰은 저장소에 저장하지 마세요.
- 현재 파이프라인은 공개 발행하지 않고, Auto-Writer가 moneynlaw 미승인/검토 대기 글까지 만드는 것을 목표로 합니다.
- 공개 발행, 승인 완료, 예약 발행, 기존 공개 기사 수정, 삭제는 별도 사용자 승인 없이는 하지 않습니다.

## 금감원 징계해설 전용 이미지 프롬프트

`article_pipeline.py`는 금감원 징계해설 기사 작업의 `auto_writer_source.md`에만 별도 이미지 프롬프트를 포함합니다. 핵심 조건은 다음과 같습니다.

- 뉴요커 만평 스타일 지향
- 검은색 펜화와 옅은 파스텔 수채화풍 채색 허용
- 오브제를 과도하게 늘리지 않음
- 인종적 혐오로 오해될 표현 회피
- 그림 안 글씨 사용 금지
- 영어 사용 금지
- 필요하면 그림 아래 한 줄 풍자 가능

## 자동 실행 방법

### 방법 A: 스크립트를 상시 실행

```bash
python monitor.py --daemon
```

### 방법 B: 작업 스케줄러

작업 스케줄러에 같은 명령을 1개 트리거로 등록합니다.

```bash
python monitor.py
```

### 방법 C: GitHub Actions로 실행

- `.github/workflows/monitor.yml` 기준으로 매시간 실행됩니다.
- GitHub Actions는 원격 저장소(`origin/main`)의 코드를 실행하므로, 로컬 수정 후 반드시 `git push`까지 해야 반영됩니다.
- GitHub secrets에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 등록하세요. 아직 Telegram을 쓰지 않으면 기존 `TEAMS_WEBHOOK_URL`로 대체 전송됩니다.
- 대량 게시가 있을 수 있으므로 기본적으로 금감원 목록 30페이지를 훑습니다. 필요하면 `FSS_MAX_LIST_PAGES` 환경변수로 늘릴 수 있습니다.

### 방법 D: 주간 상태 점검

- `.github/workflows/weekly-health-check.yml` 기준으로 매주 금요일 `15:45`(KST)에 실행됩니다.
- 최근 7일간 `monitor.yml` scheduled 실행 이력을 점검하고, 이상이 없어도 Telegram 또는 Teams로 `정상 작동 중` 메시지를 보냅니다.
- 점검 기간은 실제 워크플로 시작 시각이 아니라 주간 점검의 예정 시각(`금요일 15:45 KST`)에 고정해 계산합니다.
- 실패, 실행 누락, 미완료 run이 있으면 Telegram 또는 Teams에 `점검 필요` 상태로 요약을 보냅니다.

## 주의

- `--reset` 실행 시 기존 기록(`seen.json`)이 초기화되어 이미 있던 공시도 다시 신규로 처리됩니다.
- 첫 실행은 현재 공시 목록을 기준선으로 저장하고 알림을 보내지 않습니다. 다음 실행부터 신규만 알림합니다.
- 처음 설정 후에는 `python monitor.py --test`로 연결/설정을 먼저 확인하세요.
