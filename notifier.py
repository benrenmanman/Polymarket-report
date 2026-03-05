import requests
from datetime import datetime, timezone
from config import FEISHU_WEBHOOK


def send_feishu(text: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📊 Polymarket AI 播报"
                },
                "template": "blue"
            },
            "body": {
                "elements": [
                    {"tag": "markdown", "content": text},
                    {"tag": "hr"},
                    {"tag": "markdown", "content": f"🕐 更新时间：{now}"}
                ]
            }
        }
    }

    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()

    if result.get("code") != 0 and result.get("StatusCode") != 0:
        raise Exception(f"飞书推送失败：{result}")
