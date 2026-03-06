import requests
from config import WECOM_WEBHOOK


def send_wecom(text: str):
    """
    推送到企业微信群机器人
    文档：https://developer.work.weixin.qq.com/document/path/91770
    """
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": text
        }
    }

    r = requests.post(WECOM_WEBHOOK, json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()

    if result.get("errcode") != 0:
        raise Exception(f"企微推送失败：{result}")
