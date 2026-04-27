# fss-monitor Plan

## 1. 원래 기획 의도

이 프로젝트는 금융감독원 제재 관련 공시를 놓치지 않고 감지해 Teams로 알리고, 후속 취재/기사 작성 작업으로 자연스럽게 이어지게 만드는 자동화 프로젝트다.

초기 구현의 핵심은 금융감독원 징계공시 목록을 주기적으로 확인하고, 새 공시가 있으면 Teams에 원문 링크를 보내는 것이다. 앞으로의 확장 목표는 Teams 알림에서 끝나는 것이 아니라, 해당 공시의 PDF를 다운로드하고, Gemini의 지정 Gems를 이용해 기사 초안과 신문만평을 만들며, moneynlaw.co.kr에 기사 초안을 `기사검토=승인요청` 상태로 입력/저장하는 로컬 작업 흐름까지 연결하는 것이다.

이 문서는 프로젝트가 시간이 지나도 "무엇을 하려는 프로젝트였는지"를 잊지 않도록 유지하는 살아있는 계획 문서다. 기능 추가, 자동화 방식 변경, 운영 방식 변경, 중요한 의사결정이 생길 때마다 아래 기록을 업데이트한다.

## 2. 현재 프로젝트 상태

- 저장소 위치: `/Users/sanghoon/codes/fss-monitor`
- 현재 핵심 파일:
  - `monitor.py`: 금감원 징계공시 목록 확인, 신규 공시 감지, Teams 알림, 선택적 PDF 다운로드/Teams Graph 업로드
  - `weekly_health_check.py`: GitHub Actions 기반 모니터 실행 상태 점검
  - `.github/workflows/monitor.yml`: 매일 09:00, 16:00 KST 실행
  - `.github/workflows/weekly-health-check.yml`: 매주 금요일 15:45 KST 상태 점검
  - `seen.json`: 이미 처리한 공시 상태
- 현재 기본 동작:
  - `ALERT_LINK_ONLY=1` 기본값으로 Teams에는 링크 알림만 전송한다.
  - `ALERT_LINK_ONLY=0`과 Graph API 환경변수가 설정되면 PDF 다운로드/Teams 파일 업로드 모드가 가능하다.
- 아직 없는 것:
  - Gemini Gems 웹 UI 조작 자동화
  - moneynlaw.co.kr 기사 입력 자동화
  - 사람이 승인해야 할 지점과 완전 자동 처리 지점의 명확한 경계
- 새로 추가된 로컬 파이프라인:
  - `article_pipeline.py`: 금감원 PDF 다운로드, PDF 텍스트 추출, Gemini 입력 파일, CMS 초안 입력 템플릿, 작업 상태 파일 생성
  - `service_config.example.json`: 로컬 Gem/CMS URL 설정 예시
  - `runs/`: 기사화 작업 패키지 저장 위치. 실제 산출물은 git에 커밋하지 않는다.
  - `pipeline_state.json`: 로컬 기사화 파이프라인의 중복 처리 방지 상태 파일. git에 커밋하지 않는다.

## 3. 목표 워크플로

1. 금감원 제재 공시 신규 알림을 감지한다.
2. 해당 공시 상세 페이지에서 PDF 파일을 다운로드한다.
3. PDF 내용을 추출하거나 Gemini에 업로드 가능한 입력물로 준비한다.
4. Gemini의 "금감원 징계 해설" Gem에 PDF 내용 또는 요약 입력을 보내 기사 초안을 만든다.
5. 기사 초안을 Gemini의 "신문만평 제작" Gem에 붙여넣어 만평 이미지를 생성하고 다운로드한다.
6. 기사 초안과 만평 이미지를 moneynlaw.co.kr 회원 로그인 기반 기사 작성 화면에 입력한다.
7. 기본 운영 모드는 `기사검토=승인요청`으로 저장하기까지 진행한다. 공개 발행/승인 완료는 별도 승인 단계로 남긴다.
8. 처리 성공/실패/확인 필요 상태를 Teams 또는 로컬 로그로 남긴다.

## 4. 작업 방식

- 기존 GitHub Actions 모니터는 원격 감지와 Teams 알림의 안정적인 기반으로 유지한다.
- Gemini Gems와 moneynlaw.co.kr 작업은 로그인 세션과 브라우저 조작이 필요하므로 로컬 Mac 기반 자동화로 분리한다.
- moneynlaw.co.kr 작업은 Chrome 프로필 `가리봉동`과 회원 로그인 화면을 기본 경로로 사용한다.
- 브라우저 조작은 Playwright 또는 Computer Use 기반으로 검토한다.
- 로그인 정보, 쿠키, 세션, 비밀번호, 웹훅, API 키는 저장소에 저장하지 않는다.
- 자동화는 처음부터 완전 발행으로 가지 않고, 다운로드 -> 기사 초안 -> 만평 생성 -> CMS 승인요청 저장 순서로 단계별 검증한다.
- 각 단계는 재시도 가능하고 중복 처리되지 않도록 상태 파일을 둔다.
- 외부 웹 UI가 바뀔 수 있으므로 셀렉터/화면 탐색 실패 시 사용자에게 확인 요청이 가도록 설계한다.
- Gemini Gems를 사용할 때는 "빠른 모델" 대신 `Pro` 모델을 기본으로 선택한다.

## 5. 단계별 계획

### Phase 0. 거버넌스 문서화

- `plan.md`를 만들어 원래 기획 의도, 목표 워크플로, 현재 상태, 변경 기록을 남긴다.
- `constitution.md`를 만들어 중요한 판단 기준을 분리한다.
- `docs/agents/constitution-agent.md`와 `docs/agents/review-agent.md`를 만들어 의사결정/리뷰 절차를 고정한다.

### Phase 1. 입력과 산출물 경계 확정

- Teams 알림 링크와 `monitor.py`의 공시 상세 URL이 동일한 작업 단위로 쓰일 수 있는지 확인한다.
- PDF 다운로드가 현재 금감원 페이지 구조에서 안정적으로 동작하는지 샘플 공시로 재검증한다.
- 산출물 저장 구조를 정한다. 예: `runs/<date>_<item-id>/pdf`, `article.md`, `cartoon.png`, `status.json`.
- 초안/발행/실패/수동확인 상태를 명확히 정의한다.
- 2026-04-21 진행: `article_pipeline.py`가 `runs/<date>_<item-id>_<title>/` 구조와 `status.json`을 생성하도록 구현했다.

### Phase 2. PDF 처리와 기사 입력 준비

- 다운로드된 PDF에서 텍스트를 추출한다.
- 추출 실패 또는 표/스캔 PDF의 경우 Gemini 업로드 방식으로 우회할 수 있는지 검토한다.
- Gemini "금감원 징계 해설" Gem에 넣을 입력 형식을 정한다.
- 기사 초안 산출물을 로컬에 저장하고 재실행 시 중복 생성되지 않게 한다.
- 2026-04-21 진행: `pypdf` 기반 텍스트 추출과 `gemini_article_input.md` 생성을 구현했다. 텍스트 추출 실패 시 `manual_required` 상태와 `handoff.md`에 확인 필요 항목을 남긴다.

### Phase 3. Gemini Gems 브라우저 자동화

- 사용자가 로그인한 브라우저 프로필을 사용해 Gemini에 접근한다.
- "금감원 징계 해설" Gem에 PDF 내용/파일을 전달하고 기사 결과를 복사한다.
- "신문만평 제작" Gem에 기사 내용을 전달하고 생성 이미지를 다운로드한다.
- Gems URL, 버튼명, 다운로드 흐름이 바뀌면 실패 상태와 화면 확인 요청을 남긴다.
- 2026-04-22 진행: Silverlining Chrome 프로필에서 제공된 Gem 공유 URL이 실제 작업 가능한 내부 Gem 화면으로 연결되는지 확인했다. 공유 URL 자체가 삭제된 대화 화면을 먼저 열 수 있어, 실제 프로필에서 접근 가능한 Gem 위치를 `service_config.local.json`에 갱신했다.
- 2026-04-22 진행: "금감원 징계 해설" Gem에 하나은행 제재 공시 PDF 추출 내용을 입력해 기사 초안을 생성했고, 결과를 `runs/.../article.md`에 저장했다.
- 2026-04-22 진행: "신문만평 제작" Gem에 기사 전문을 입력해 만평 이미지를 생성했고, 원본 크기 PNG를 다운로드해 `runs/.../cartoon/cartoon.png`에 보관했다.

### Phase 4. moneynlaw.co.kr CMS 입력 자동화

- 회원 로그인 URL, 로그인 상태, 기사 작성 화면 구조를 확인한다.
- 제목, 본문, 카테고리, 태그, 대표이미지/본문이미지 입력 규칙을 정한다.
- 기본은 `기사검토=승인요청`으로 구현하고, 입력과 이미지 첨부가 끝나면 `저장하기`까지 누른다.
- 자동 발행/승인 완료는 사용자에게 별도 확인을 받은 뒤 constitution 기준에 따라 결정한다.
- 2026-04-22 진행: Silverlining Chrome 프로필에서 moneynlaw 관리자 화면 로그인 상태를 확인했고, 작성 URL이 `modify&idxno=476` 초안 작업 화면으로 전환되는 것을 확인했다.
- 2026-04-22 진행: CMS 필드 매핑을 확인했다. 등급은 중요기사, 상태는 미승인, 1차섹션은 경제, 2차섹션은 미선택 상태, 연재는 금감원 제재 공시 분석, 기자는 기본값 머니앤로로 입력한다.
- 2026-04-22 진행: 기사 제목, 본문, 만평 이미지를 CMS 화면에 입력했다. CMS가 일부 변경을 자동 임시저장하는 동작을 보였으나, `저장하기` 버튼은 사용자 확인 전까지 누르지 않는다.
- 2026-04-22 변경: 위 Silverlining/관리자 로그인/등급·상태 중심 흐름은 초기 검증 기록으로 남기되, 이후 운영 기준은 Chrome 프로필 `가리봉동`, 회원 로그인 URL, `기사검토=승인요청`, 입력 후 `저장하기`로 바꾼다.

### Phase 5. 운영 안정화

- 실패 시 재시도/중단/수동 확인 정책을 정한다.
- Teams에 처리 결과 요약을 보낼지 결정한다.
- 로컬 Mac이 꺼져 있거나 잠겨 있을 때는 웹 UI 자동화가 동작하지 않는다는 제한을 명확히 알린다.
- 필요하면 Gemini API 또는 CMS API 방식으로 장기 안정화 가능성을 검토한다.
- 다른 기기에서 이어갈 가능성이 있으면, 로컬 전용 `runs/`와 별도로 비밀이 없는 인계 패키지를 추적 경로에 남기는 절차를 둔다.
- 기기 이동 시에는 새 머신 인계만 하지 말고, 이전 머신의 `cron`/`launchd`/수동 daemon 실행 경로도 함께 정리한다.

## 6. 사용자에게 필요한 정보

- Gemini 로그인 상태 또는 로그인 가능한 브라우저 프로필
- Gemini Gems 모델 선택: 2026-04-22 기준 `Pro` 사용. "빠른 모델"은 기본으로 쓰지 않는다.
- Gemini "금감원 징계 해설" Gem의 접근 URL 또는 정확한 위치: 2026-04-21 제공 완료. 기본값은 `service_config.local.json`에만 저장하지만, 사용자가 다른 기기에서 이어가야 한다고 명시하면 `handoff/` 문서에 예외적으로 기록할 수 있다.
- Gemini "신문만평 제작" Gem의 접근 URL 또는 정확한 위치: 2026-04-21 제공 완료. 기본값은 `service_config.local.json`에만 저장하지만, 사용자가 다른 기기에서 이어가야 한다고 명시하면 `handoff/` 문서에 예외적으로 기록할 수 있다.
- moneynlaw.co.kr 회원 로그인 URL: 2026-04-22 기준 `https://www.moneynlaw.co.kr/member/login.html` 사용. 실제 실행 URL은 `service_config.local.json`에 저장한다.
- Chrome 프로필: 2026-04-22 기준 `가리봉동` 사용. 로컬 Chrome 프로필 디렉터리는 `Profile 4`로 확인했다. 계정 확인 힌트는 로컬 설정에만 둔다.
- moneynlaw.co.kr 계정 권한과 2FA 방식
- 기사 입력 규칙:
  - 카테고리
  - 작성자
  - 태그
  - 출처 표기 방식
  - 대표이미지/본문이미지 사용 방식
  - `기사검토=승인요청` 저장 또는 즉시 발행 여부
- 실패 시 알림을 받을 채널

## 7. 결정 기록

### 2026-04-21

- 결정: 이 프로젝트의 다음 확장 목표를 "금감원 공시 감지 -> PDF 다운로드 -> Gemini 기사 초안 -> Gemini 만평 생성 -> moneynlaw 기사 입력"으로 기록한다.
- 결정: Gemini Gems와 moneynlaw.co.kr 작업은 GitHub Actions가 아니라 로컬 Mac 브라우저 자동화 영역으로 분리한다.
- 결정: 기본 CMS 동작은 즉시 발행이 아니라 초안 저장으로 둔다. 자동 발행은 별도 사용자 확인 전까지 구현하지 않는다. 2026-04-22에 기본 저장 단계가 `기사검토=승인요청`으로 구체화됐다.
- 결정: 판단 기준은 `constitution.md`에 분리하고, 애매하거나 중요한 결정은 constitution agent 절차를 따른다.
- 결정: 변경 후에는 review agent 절차로 코드/문서/의사결정 흐름을 점검한다.
- 결정: 실제 서비스 1차 구현은 Gemini/CMS 자동 조작보다 앞서 로컬 작업 패키지 생성으로 시작한다. 이유는 로그인 정보와 사용자 확인 없이도 PDF 다운로드, 텍스트 추출, Gemini 입력 준비, CMS 초안 템플릿까지 안전하게 검증할 수 있기 때문이다.
- 결정: `runs/`, `pipeline_state.json`, `service_config.local.json`, `pdfs/`는 로컬 산출물/설정으로 보고 git에서 제외한다.
- 결정: Gemini Gem 공유 URL과 moneynlaw 로그인/작성 URL은 자동화 실행에 필요한 로컬 설정으로 취급한다. 기본적으로 tracked 문서에는 제공/설정 여부만 기록하고, 실제 운영 기준은 예시 설정과 `service_config.local.json`에 둔다. 다만 사용자가 기기 이동 인계를 명시하면, 비비밀 URL은 `handoff/` 문서에 예외적으로 기록할 수 있다.
- 결정: Gemini 공유 URL이 프로필별 실제 Gem 화면으로 바로 이어지지 않을 수 있으므로, 실행 가능한 Gem 위치는 로컬 설정에만 갱신하고 tracked 문서에는 노출하지 않는다.
- 결정: moneynlaw 작성 화면의 `저장하기`는 기사 저장을 확정하는 대표적 외부 서비스 조작으로 보고, 사용자 확인 없이 누르지 않는다. 자동 임시저장은 CMS 자체 동작이므로 작업 기록에 별도로 남긴다. 2026-04-22에 `기사검토=승인요청` 저장은 공개 발행이 아니라 최종 승인 대기 단계이므로 추가 확인 없이 누르는 것으로 변경됐다.

### 2026-04-22

- 결정: Gemini Gems 실행 시 "빠른 모델" 대신 `Pro`를 기본 모델로 사용한다. 사용자가 품질 차이가 크다고 판단했으므로, 기사 초안과 만평 생성 모두 이 기준을 따른다.
- 결정: moneynlaw.co.kr 작업은 Chrome 프로필 `가리봉동`을 사용한다. 계정 힌트와 저장된 로그인 정보는 로컬 프로필/로컬 설정에만 둔다.
- 결정: moneynlaw.co.kr 로그인은 관리자 로그인 화면 대신 회원 로그인 화면 `https://www.moneynlaw.co.kr/member/login.html`을 사용한다. 관리자가 아닌 회원 로그인 경로가 더 안전하다는 사용자 판단을 따른다.
- 결정: 기사 작성 화면에서는 등급/상태 시작 흐름이 아니라 `기사검토` 항목에서 `승인요청`을 선택한다.
- 결정: 기사 입력과 이미지 입력이 완료되면 `저장하기`를 누른다. `승인요청` 저장은 최종 공개 발행 전 단계이므로 추가 사용자 확인을 요구하지 않는다.

### 2026-04-27

- 결정: `runs/`와 `service_config.local.json`은 계속 로컬 전용으로 유지한다.
- 결정: 사용자가 다른 기기에서 이어가야 한다고 명시하면, 비밀이 없는 현재 작업 산출물은 `handoff/` 아래 추적 파일로 승격해 GitHub에 저장한다.
- 결정: 기기 이동 인계를 위해 Gem URL 같은 비비밀 설정값은 추적 문서에 기록할 수 있지만, 계정 힌트, 로그인 세션, 쿠키, 비밀번호는 계속 로컬에만 둔다.
- 결정: 이전 머신을 실행 경로에서 제외할 때는 해당 머신에 남아 있는 `cron`, `launchd`, 수동 daemon 경로를 제거하거나 중단한다.
- 결정: 새 로컬 Mac의 기준 저장소 위치를 `/Users/sanghoon/codes/fss-monitor`로 삼고, 이전 기기 경로(`/Users/air/...`)는 과거 기록 또는 인계 맥락으로만 취급한다.

## 8. 작업 기록

### 2026-04-21

- `plan.md` 최초 작성.
- `constitution.md` 최초 작성.
- `docs/agents/constitution-agent.md` 최초 작성.
- `docs/agents/review-agent.md` 최초 작성.
- 루트 `AGENTS.md`를 추가해 존대말, `trash` 사용, plan/constitution/review 절차를 저장소 작업 규칙으로 명시.
- `article_pipeline.py` 추가. 최신 공시 또는 지정 URL을 기준으로 PDF 다운로드, PDF 텍스트 추출, Gemini 입력 파일, 만평 입력 템플릿, CMS 입력 템플릿, handoff/status 파일을 생성한다.
- `service_config.example.json` 추가. Gem URL과 CMS 로그인/작성 URL을 저장소에 비밀 없이 연결하기 위한 로컬 설정 예시를 제공한다.
- `.gitignore` 업데이트. 로컬 산출물과 설정 파일을 커밋하지 않도록 제외했다.
- `requirements.txt`에 `pypdf` 추가.
- README에 로컬 기사화 파이프라인 사용법을 추가했다.
- 검증: `.venv/bin/python article_pipeline.py --latest --force --no-state` 실행으로 2026.04.20 `주식회사 하나은행 제재관련 공시` PDF 1건을 다운로드하고 텍스트 추출 및 `gemini_ready` 상태 생성까지 확인했다.
- 사용자가 Gemini "금감원 징계 해설" Gem URL, Gemini "신문만평 제작" Gem URL, moneynlaw 관리자 로그인 URL을 제공했다.
- 제공된 URL을 `service_config.local.json`에 저장했다. 이 파일은 `.gitignore` 대상이라 커밋하지 않는다.
- Silverlining Chrome 프로필에서 Gemini "금감원 징계 해설" Gem에 PDF 추출 내용을 입력하고 기사 초안을 생성했다.
- 생성된 기사 초안을 `runs/20260420_202500146_1_주식회사-하나은행-제재관련-공시/article.md`로 저장했다.
- Silverlining Chrome 프로필에서 Gemini "신문만평 제작" Gem에 기사 전문을 입력하고 만평 이미지를 생성했다.
- 생성된 만평 이미지를 다운로드하고 `runs/20260420_202500146_1_주식회사-하나은행-제재관련-공시/cartoon/cartoon.png`에 보관했다.
- moneynlaw 관리자 작성 화면에서 `idxno=476` 초안에 등급, 상태, 섹션, 연재, 제목, 본문, 만평 이미지를 입력했다.
- `저장하기` 버튼은 아직 누르지 않았다. 다음 단계는 사용자 확인 후 저장 버튼을 누르거나, 사용자가 직접 화면을 검토하는 것이다.

### 2026-04-22

- Gemini Gems 모델 선택 기준을 `Pro`로 고정했다.
- `article_pipeline.py`, `service_config.example.json`, `README.md`, `constitution.md`에 Gemini 모델 모드 기본값과 작업 지침을 반영했다.
- moneynlaw 운영 경로를 Chrome 프로필 `가리봉동`, 회원 로그인 URL, `기사검토=승인요청`, 입력 후 `저장하기` 기준으로 변경했다.
- 로컬 Chrome 설정에서 `가리봉동` 프로필의 디렉터리가 `Profile 4`임을 확인하고 `service_config.local.json`에 반영했다.
- `article_pipeline.py`, `service_config.example.json`, `README.md`, `constitution.md`, `docs/agents/constitution-agent.md`에 새 CMS 저장 기준을 반영했다.
- Chrome 프로필 `가리봉동`에서 moneynlaw 회원 로그인 화면을 통해 로그인하고, 회원 기사작성 화면에서 기사번호 `478`을 생성/저장했다.
- 기사번호 `478`은 `기사검토=승인요청`, 1차섹션 `경제`, 연재 `금감원 제재 공시 분석`, 제목 `하나은행, 실명확인 의무 위반 징계`, 본문 및 만평 이미지 입력 상태로 저장됐다.
- 이전 Silverlining/관리자 작성 초안 `idxno=476`은 초기 검증 기록으로만 남기고, 현재 작업 기준과 산출 상태는 회원 작성 기사 `idxno=478`로 대체한다.
- 기본 CMS 작성 URL을 관리자 작성 화면에서 회원 작성 화면 `https://www.moneynlaw.co.kr/news/userArticleWriteForm.html`로 변경했다.

### 2026-04-27

- 다른 기기에서 이어가기 쉽게 하라는 사용자 요청에 따라, 현재 산출물을 `handoff/20260420_202500146_1_주식회사-하나은행-제재관련-공시/`로 승격해 GitHub에 보존하는 정리 작업을 진행한다.
- `runs/` 정책은 유지하고, 비밀이 없는 기사 초안, 만평 이미지, PDF 텍스트, 원문 PDF, 현재 상태 요약만 추적 인계 패키지로 복사한다.
- 새 기기용 재설정 절차와 로컬 전용 정보의 경계를 README 및 인계 문서에 기록한다.
- 이 머신에서 더 이상 작업을 실행하지 않겠다는 사용자 지시에 따라, 로컬 실행 흔적을 점검했다. `launchctl`에는 관련 작업이 없었고, `crontab`에는 `monitor.py` 항목이 남아 있어 제거 대상으로 확인했다.
- GitHub 저장소 `https://github.com/coolpint/fss-monitor`를 새 로컬 Mac의 `/Users/sanghoon/codes/fss-monitor`에 clone 했다.
- README와 인계 문서의 로컬 파일 링크를 새 기준 경로(`/Users/sanghoon/codes/fss-monitor`)로 정정했다.
- 비밀이 아닌 Gem/CMS URL과 기본 운영값을 바탕으로 새 로컬 전용 `service_config.local.json`을 생성한다. 로그인 세션, 쿠키, 계정 힌트, 비밀번호는 저장하지 않는다.
- 새 로컬 전용 Python 가상환경 `.venv/`를 만들 예정이므로 `.gitignore`에 `.venv/`를 추가한다.
- macOS 기본 Python 3.9의 LibreSSL 환경에서 `urllib3 v2` 경고가 발생하므로, 이 로컬 이관 기준에서는 `urllib3<2`를 명시해 실행 로그와 HTTPS 호환성을 안정화한다.
- 코드 재점검 결과, Teams Webhook은 코드 기본값이 아니라 환경변수/Actions secret으로만 주입하도록 정리한다.
- `monitor.py --reset`은 파일 삭제 대신 `trash` 명령으로 `seen.json`을 휴지통으로 이동하도록 바꾼다.
- GitHub Actions 상태 저장은 `git add -A` 대신 `seen.json`만 staging해 의도치 않은 파일 커밋을 막는다.
- 로컬 작업 산출물에 계정 힌트 값이 직접 기록되지 않도록, handoff/CMS 템플릿/metadata에는 설정 여부 또는 로컬 보관 안내만 남긴다.
- 로컬 Mac의 Python 3.9에서도 주간 점검 스크립트가 import되도록 `datetime.UTC` 대신 `timezone.utc` 호환 방식을 사용한다.
- 검증: `monitor.py --test`는 실제 금감원 사이트에서 공시 후보 10건을 파싱했고, `TEAMS_WEBHOOK_URL`이 없을 때 Teams 전송을 안전하게 건너뛰는 것을 확인했다.
- 검증: `article_pipeline.py --latest --force --no-state --max-items 1`로 최신 하나은행 공시의 PDF 다운로드, 텍스트 추출, Gemini/CMS 인계 파일 생성이 `gemini_ready` 상태까지 완료되는 것을 확인했다.
- 검증: `weekly_health_check.py --repository coolpint/fss-monitor --print-only --lookback-days 1`로 GitHub Actions 주간 점검 API 조회가 정상 동작하는 것을 확인했다.
- 검증: `monitor.py` 1회 실행은 현재 `seen.json` 기준으로 공시 후보 10건 확인 후 `새로운 공시 없음` 상태로 정상 종료됐다.

## 9. 변경 기록

### 2026-04-21

- 프로젝트 거버넌스 문서 세트를 도입했다.
- 기존 Teams 링크 알림 모니터의 목적을 보존하면서, 후속 기사/만평/CMS 자동화 확장 의도를 명문화했다.
- 실제 서비스 1차 구현으로 로컬 기사화 파이프라인을 도입했다.
- Gemini/CMS 직접 조작은 로그인/권한/URL 확인 후 다음 단계에서 붙이는 것으로 남겼다.
- 샘플 작업 산출물은 `runs/` 아래 생성되며 git에는 커밋하지 않는다.
- Gemini/CMS URL 설정이 확보되어 Phase 3/4 브라우저 자동화 검증으로 넘어갈 수 있게 됐다.
- Phase 3/4 브라우저 기반 수동-반자동 검증을 1건 완료했다. 기사와 만평은 생성됐고 CMS 입력도 완료됐으나, 최종 저장 버튼은 사용자 확인 전까지 보류한다.

### 2026-04-22

- Gemini Gems 실행 기본 모델을 `Pro`로 변경했다. 향후 handoff와 생성 프롬프트에는 모델 선택 지침이 포함된다.
- moneynlaw CMS 흐름을 관리자 로그인/미승인 상태 중심에서 회원 로그인/`기사검토=승인요청` 중심으로 변경했다.
- `승인요청` 상태의 `저장하기`는 공개 발행이 아니라 최종 승인 대기 단계이므로, 기사와 이미지 입력이 완료되면 자동화가 추가 확인 없이 누르는 기준으로 바꿨다.
- 실제 CMS 저장까지 완료한 기준 기사번호는 `478`이다. 저장 후 기사보기 화면에서 상태가 `승인요청`으로 표시됨을 확인했다.
- `article_pipeline.py`, `service_config.example.json`, `service_config.local.json`의 기본 작성 URL을 회원 작성 URL로 정정했다.

### 2026-04-27

- 기기 이동을 위한 추적 인계 패키지 방식을 도입했다. 기본 로컬 산출물 정책은 유지하되, 명시적 요청 시 `handoff/` 아래에 비밀 없는 산출물을 Git-tracked 형태로 보존한다.
- 이 머신은 더 이상 이 프로젝트의 실행 경로로 사용하지 않기로 했고, 남아 있던 로컬 스케줄 흔적을 정리하는 절차를 문서와 운영 기록에 반영했다.
- 저장소를 새 로컬 Mac으로 가져오고 문서의 기준 경로를 `/Users/sanghoon/codes/fss-monitor`로 갱신했다.
- 새 로컬 Mac의 Python 실행 환경 준비를 위해 `.venv/`를 로컬 전용 제외 대상으로 추가했다.
- macOS 기본 Python 3.9에서 발생한 `urllib3 v2` LibreSSL 경고를 피하기 위해 `requirements.txt`에 `urllib3<2`를 추가했다.
- 코드 재점검으로 비밀 정보 주입, reset 파일 처리, Actions 상태 커밋 범위, 로컬 계정 힌트 기록 방식을 constitution 기준에 맞게 정리했다.
- `weekly_health_check.py`가 Python 3.9 로컬 환경에서도 실행될 수 있도록 UTC 상수를 호환 방식으로 수정했다.
- 실제 네트워크 검증으로 금감원 목록 파싱, 기사화 작업 패키지 생성, GitHub Actions 점검 조회가 새 로컬 Mac에서 동작함을 확인했다.
- 1회 모니터 실행까지 확인해 GitHub Actions 감시 흐름과 로컬 기사화 흐름이 모두 이어질 수 있는 상태로 정리했다.
