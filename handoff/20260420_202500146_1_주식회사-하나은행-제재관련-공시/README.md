# 하나은행 제재관련 공시 인계 보관본

이 폴더는 2026-04-20 하나은행 제재관련 공시의 과거 산출물 보관본입니다.

현재 운영 기준은 이 폴더의 과거 실행 방식이 아니라 루트 `plan.md`의 Telegram 알림 + Auto-Writer 인계 방식입니다.

## 보관 파일

- `article.md`: 당시 작성된 기사 초안
- `pdf_text.txt`: 공시 PDF 추출 텍스트
- `source.pdf`: 원문 PDF 보관본
- `cartoon.png`: 당시 생성된 이미지 보관본
- `metadata.json`, `status.json`: 당시 상태 요약

## 주의

- 이 보관본에는 현재 실행 절차가 없습니다.
- 새 공시 처리는 루트의 `article_pipeline.py`가 생성하는 `auto_writer_*` 파일을 기준으로 합니다.
- 로그인 세션, 계정 힌트, API 키, 외부 생성 도구 URL은 저장소에 남기지 않습니다.
