import requests
import base64
import hashlib
from config import WECOM_WEBHOOK   # 原有配置，保持不动

# template_card horizontal_content_list 最多支持 6 条
_CARD_MAX_ITEMS = 6


def send_summary_card(slug_data: list, overall_analysis: str, timestamp: str):
    """
    在所有 slug 详细报告前发送一条汇总消息。
    优先使用企业微信模板卡片（text_notice），超过 6 条或失败时降级为 Markdown。

    slug_data: [{"slug": ..., "question": ..., "yes_price": float|None,
                 "is_multi": bool, "sub_count": int}, ...]
    overall_analysis : AI 整体解读文字
    timestamp        : 更新时间字符串，如 "2024-01-01 12:00 UTC"
    """
    n = len(slug_data)

    def _price_str(d: dict) -> str:
        if d.get("is_multi"):
            return f"多选项 ({d.get('sub_count', 0)} 个)"
        yp = d.get("yes_price")
        return f"{yp:.1%}" if yp is not None else "N/A"

    # ── 尝试 template_card（≤6 条时）──
    if n <= _CARD_MAX_ITEMS:
        items = [
            {"keyname": d["question"][:24], "value": _price_str(d)}
            for d in slug_data
        ]
        payload = {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "text_notice",
                "source": {
                    "desc": "Polymarket 市场监控",
                    "desc_color": 0,
                },
                "main_title": {
                    "title": "📊 市场概览",
                    "desc": timestamp,
                },
                "emphasis_content": {
                    "title": str(n),
                    "desc": "个监控市场",
                },
                "horizontal_content_list": items,
                "card_action": {"type": 0},
            },
        }
        try:
            resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
            if resp.json().get("errcode", -1) == 0:
                send_markdown(f"**整体市场解读：**\n\n{overall_analysis}")
                return
        except Exception:
            pass   # 降级到 Markdown

    # ── 降级：Markdown ──
    lines = ["## 📊 Polymarket 市场概览", f"> 更新时间：{timestamp}", ""]
    for d in slug_data:
        lines.append(f"- **{d['question']}**：{_price_str(d)}")
    lines += ["", "**整体市场解读：**", overall_analysis]
    send_markdown("\n".join(lines))


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
