# 기기 이동 인계서

## 작업 단위

- 금감원 공시 ID: `202500146_1`
- 공시명: `주식회사 하나은행 제재관련 공시`
- 공시일: `2026.04.20`
- 원문 URL: [금감원 공시](https://www.fss.or.kr/fss/job/openInfo/view.do?menuNo=200476&sdate=2026-01-01&edate=2026-04-21&pageIndex=1&examMgmtNo=202500146&emOpenSeq=1)

## 현재까지 완료된 상태

- PDF 다운로드 완료
- PDF 텍스트 추출 완료
- Gemini 기사 초안 생성 완료
- Gemini 만평 생성 및 다운로드 완료
- moneynlaw 회원 작성 기사 저장 완료
- 저장된 기사 번호: `478`
- 저장 상태: `기사검토=승인요청`
- 기사 보기 URL: [moneynlaw 기사보기](https://www.moneynlaw.co.kr/news/userWriterArticleView.html?idxno=478)

## 이 폴더에 담긴 파일

- [article.md](./article.md): 생성된 기사 초안
- [pdf_text.txt](./pdf_text.txt): PDF 추출 텍스트
- [source.pdf](./source.pdf): 원문 PDF
- [cartoon.png](./cartoon.png): Gemini 만평 이미지

## 새 기기에서 해야 할 일

1. 이 저장소를 clone 한다.
2. [service_config.example.json](/Users/sanghoon/codes/fss-monitor/service_config.example.json)을 복사해 `service_config.local.json`을 만든다.
3. `service_config.local.json`에 아래 값을 채운다.
   - `gemini_model_mode`: `Pro`
   - `article_gem_url`: `https://gemini.google.com/gem/ac8fb39d6b37`
   - `cartoon_gem_url`: `https://gemini.google.com/gem/a750fbd15cf7`
   - `cms_login_url`: `https://www.moneynlaw.co.kr/member/login.html`
   - `cms_write_url`: `https://www.moneynlaw.co.kr/news/userArticleWriteForm.html`
   - `cms_review_status`: `승인요청`
4. Chrome에 새 로컬 프로필을 준비하고 Gemini, moneynlaw에 로그인한다.
5. `chrome_profile_name`은 기본값 `가리봉동`을 써도 되지만, 새 기기에서 실제 프로필 디렉터리는 다를 수 있으므로 `chrome_profile_directory`는 현지 환경에 맞게 다시 확인한다.
6. 현재 저장된 기사 `478`을 위 기사보기 URL로 열어 상태를 확인한다.
7. 후속 작업은 다음 둘 중 하나로 이어간다.
   - 새 공시 처리: `python article_pipeline.py --process-new`
   - 현재 공시 재검토: 이 폴더의 `article.md`, `cartoon.png`, `source.pdf`를 기준으로 수동 보완

## GitHub에 남기지 않은 정보

- Gemini/moneynlaw 로그인 세션
- Chrome 쿠키와 저장된 비밀번호
- 계정 힌트 이메일
- 새 기기에서 달라질 수 있는 실제 Chrome 프로필 디렉터리 값
- 이후 누적될 `runs/`, `pipeline_state.json`

## 메모

- 이 인계 패키지는 "현재까지의 작업을 다른 기기에서 이어가기 위한 스냅샷"이다.
- 기본 운영 정책은 여전히 `runs/` 로컬 작업 디렉터리를 쓰는 것이고, `handoff/`는 예외적인 기기 이동 상황에서만 사용한다.
