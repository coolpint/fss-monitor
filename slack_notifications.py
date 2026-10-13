"""Slack 전용 발송. 인증정보와 응답 본문을 로그에 남기지 않는다."""

import requests
import re
from urllib.parse import urlparse

TARGET_SLACK_CHANNEL_ID = "C0C9LQN7A64"  # 사용자 요청으로 생성·확인된 #fss-monitor
TARGET_SLACK_WORKSPACE_ID = "T054M7CUG"


def valid_webhook_url(webhook_url: str) -> bool:
    try:
        url = urlparse(webhook_url)
        return (url.scheme == "https" and url.netloc == "hooks.slack.com"
                and not url.query and not url.fragment
                and bool(re.fullmatch(r"/services/" + TARGET_SLACK_WORKSPACE_ID + r"/[A-Z0-9]+/[A-Za-z0-9_-]+", url.path)))
    except ValueError:
        return False


def send_slack_message(text: str, webhook_url: str, channel_id: str) -> bool:
    # URL에서 channel ID는 확인할 수 없다. 승인된 생성 화면과 첫 수신으로
    # 연결을 검증한다. channel_id는 로컬 설정 실수 방지용이다.
    if not valid_webhook_url(webhook_url) or channel_id != TARGET_SLACK_CHANNEL_ID:
        print("⚠ 승인된 SLACK_WEBHOOK_URL과 확인된 SLACK_CHANNEL_ID가 필요합니다.")
        return False
    try:
        # 불확실한 연결 실패에서 중복 발송을 줄이기 위해 자동 재시도하지 않는다.
        response = requests.post(
            webhook_url,
            json={"text": text, "mrkdwn": False,
                  "unfurl_links": False, "unfurl_media": False},
            timeout=20,
            allow_redirects=False,
        )
        if response.status_code != 200:
            print(f"⚠ Slack 발송 실패: HTTP {response.status_code}")
            return False
        if response.text.strip() != "ok":
            print("⚠ Slack 발송 실패: webhook 성공 응답 확인 불가")
            return False
    except Exception:
        print("⚠ Slack 발송 실패: 연결 또는 응답 오류 (본문/인증정보 생략)")
        return False
    print("✓ Slack 알림 발송 완료")
    return True
