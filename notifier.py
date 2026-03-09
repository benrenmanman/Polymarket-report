import requests
import base64
import hashlib
from config import WECOM_WEBHOOK   # 原有配置，保持不动


def send_text(content: str):
    """原有函数，保持不变"""
    payload = {"msgtype": "text", "text": {"content": content}}
    requests.post(WECOM_WEBHOOK, json=payload, timeout=10)


def send_markdown(content: str):
    """原有函数（如有），保持不变"""
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    requests.post(WECOM_WEBHOOK, json=payload, timeout=10)


def send_image(image_bytes: bytes):
    """
    新增：发送图片到企业微信。
    image_bytes : PNG/JPG 的原始字节（由 analyzer.plot_highfreq 返回）
    """
    if not image_bytes:
        return
    b64    = base64.b64encode(image_bytes).decode("utf-8")
    md5    = hashlib.md5(image_bytes).hexdigest()
    payload = {
        "msgtype": "image",
        "image": {
            "base64": b64,
            "md5"   : md5,
        },
    }
    resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=15)
    resp.raise_for_status()


def send_highfreq_report(question: str, analysis: str, chart_bytes: bytes):
    """
    新增：组合发送高频报告（文字 + 图片）。
    question    : 市场问题文本
    analysis    : analyze_highfreq() 返回的 AI 解读文字
    chart_bytes : plot_highfreq() 返回的 PNG bytes
    """
    # 1. 先发文字解读
    text = f"📊 **{question}**\n\n{analysis}"
    send_markdown(text)

    # 2. 再发走势图
    if chart_bytes:
        send_image(chart_bytes)
