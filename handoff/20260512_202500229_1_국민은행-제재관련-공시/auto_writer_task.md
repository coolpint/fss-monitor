# Auto-Writer 기사화 작업

PDF 다운로드와 텍스트 추출 이후 단계는 Auto-Writer가 맡습니다.

## 작업 폴더

- 경로: `/Users/sanghoon/codes/fss-monitor/handoff/20260512_202500229_1_국민은행-제재관련-공시`
- 공시명: 국민은행 제재관련 공시
- 공시일: 2026.05.12
- 원문 URL: https://www.fss.or.kr/fss/job/openInfo/view.do?menuNo=200476&sdate=2026-01-01&edate=2026-05-18&pageIndex=1&examMgmtNo=202500229&emOpenSeq=1

## 실행 가능 여부

- 실행 가능: 예
- 차단 사유:
- 없음
- PDF/텍스트 추출 오류:
- 없음

## Auto-Writer 실행

- Auto-Writer 프로젝트: `/Users/sanghoon/codes/Auto-Writer`
- 입력 파일: `/Users/sanghoon/codes/fss-monitor/handoff/20260512_202500229_1_국민은행-제재관련-공시/auto_writer_source.md`
- 모드: `live`
- 채널: `fss-monitor`
- CMS 기사검토 상태: `미승인`

```bash
cd /Users/sanghoon/codes/Auto-Writer
node src/index.js run --mode live --channel fss-monitor --source /Users/sanghoon/codes/fss-monitor/handoff/20260512_202500229_1_국민은행-제재관련-공시/auto_writer_source.md
```

## 안전 기준

- moneynlaw 저장 상태는 `미승인`로 둡니다.
- 공개 발행, 승인 완료, 예약 발행, 기존 공개 기사 수정, 삭제는 하지 않습니다.
- 금감원 징계해설 기사 이미지에는 `auto_writer_source.md`의 전용 이미지 프롬프트를 사용합니다.
- 저장 결과의 작업 폴더, CMS 상태, 기사 URL/ID가 확인되면 `auto_writer_state.json`에 기록합니다.
