# 금감원 징계공시 모니터링

금감원에 새 징계공시가 올라오면 PDF를 다운로드하고 Teams에 알려줍니다.

## 설치 (한 번만)

1. Python 설치 (https://www.python.org → 3.12 다운로드, 설치 시 "Add to PATH" 체크)

2. 명령 프롬프트(cmd)에서 실행:
   cd 이_폴더_경로
   pip install -r requirements.txt

3. Teams에서 Incoming Webhook 만들기:
   - 알림 받을 채널 → ··· → 커넥터 → Incoming Webhook → 구성
   - URL 복사

4. monitor.py를 메모장으로 열어서 맨 위의 TEAMS_WEBHOOK_URL에 복사한 URL 붙여넣기

5. 테스트:
   python monitor.py --test

## 사용

python monitor.py          ← 새 공시 확인 (매일 실행)
python monitor.py --test   ← 연결 테스트
python monitor.py --reset  ← 기록 초기화

## 매일 자동 실행

Windows 작업 스케줄러에 등록하면 매일 자동 실행됩니다.
1. Win+R → taskschd.msc
2. 기본 작업 만들기
3. 매일 오전 9시
4. 프로그램: python, 인수: monitor.py, 시작 위치: 이 폴더 경로
