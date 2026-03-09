import requests
import base64
import hashlib
from config import WECOM_WEBHOOK


def send_text(content: str):
    """发送纯文本消息"""
    payload = {"msgtype": "text", "text": {"content": content}}
    requests.post(WECOM_WEBHOOK, json=payload, timeout=10)


def send_markdown(content: str):
    """发送 markdown 消息（支持字体颜色/@成员，不支持表格）"""
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    requests.post(WECOM_WEBHOOK, json=payload, timeout=10)


def send_markdown_v2(content: str):
    """
    发送 markdown_v2 消息（支持表格/列表/代码块，不支持字体颜色/@成员）
    客户端需 4.1.36+ 版本，旧版降级为纯文本。
    内容最长 4096 字节。
    """
    payload = {"msgtype": "markdown_v2", "markdown_v2": {"content": content}}
    resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def send_image(image_bytes: bytes):
    """发送图片（PNG/JPG，≤2MB）"""
    if not image_bytes:
        return
    b64  = base64.b64encode(image_bytes).decode("utf-8")
    md5  = hashlib.md5(image_bytes).hexdigest()
    payload = {
        "msgtype": "image",
        "image": {"base64": b64, "md5": md5},
    }
    resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=15)
    resp.raise_for_status()


def send_highfreq_report(question: str, analysis: str, chart_bytes: bytes):
    """发送单市场高频报告（文字 + 走势图）"""
    text = f"📊 **{question}**\n\n{analysis}"
    send_markdown(text)
    if chart_bytes:
        send_image(chart_bytes)
