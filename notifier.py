import time
import requests
import base64
import hashlib
from config import WECOM_WEBHOOK, CORP_ID, CORP_SECRET, AGENT_ID

# template_card horizontal_content_list 最多支持 6 条
_CARD_MAX_ITEMS = 6

# ── access_token 本地缓存（进程内有效）──
_token_cache: dict = {"token": "", "expires_at": 0.0}

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"


# ──────────────────────────────────────────
# 企业微信应用消息 API 辅助函数
# ──────────────────────────────────────────
def get_access_token() -> str:
    """获取企业微信 access_token，自动缓存（提前 60s 刷新）。"""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    resp = requests.get(
        f"{WECOM_API}/gettoken",
        params={"corpid": CORP_ID, "corpsecret": CORP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"get_access_token 失败: {data}")
    _token_cache["token"]      = data["access_token"]
    _token_cache["expires_at"] = time.time() + data["expires_in"] - 60
    return _token_cache["token"]


def upload_image_for_mpnews(image_bytes: bytes) -> str:
    """
    将 PNG 图片上传至企业微信，返回可嵌入 mpnews HTML 内容的永久图片 URL。
    接口：POST /media/uploadimg
    """
    token = get_access_token()
    resp = requests.post(
        f"{WECOM_API}/media/uploadimg",
        params={"access_token": token},
        files={"media": ("chart.png", image_bytes, "image/png")},
        timeout=20,
    )
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"uploadimg 失败: {data}")
    return data["url"]


def upload_media_thumb(image_bytes: bytes) -> str:
    """
    将 PNG 图片作为临时素材上传，返回 media_id（用作 mpnews 缩略图）。
    接口：POST /media/upload?type=image
    """
    token = get_access_token()
    resp = requests.post(
        f"{WECOM_API}/media/upload",
        params={"access_token": token, "type": "image"},
        files={"media": ("thumb.png", image_bytes, "image/png")},
        timeout=20,
    )
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"upload_media 失败: {data}")
    return data["media_id"]


def send_mpnews(articles: list, touser: str = "@all"):
    """
    通过企业微信应用消息接口发送 mpnews 图文消息。
    articles 格式：
      [{"title":..., "thumb_media_id":..., "author":...,
        "content":..., "digest":..., "content_source_url":...}]
    接口：POST /message/send
    """
    token = get_access_token()
    payload = {
        "touser":   touser,
        "msgtype":  "mpnews",
        "agentid":  AGENT_ID,
        "mpnews":   {"articles": articles},
        "enable_duplicate_check": 0,
    }
    resp = requests.post(
        f"{WECOM_API}/message/send",
        params={"access_token": token},
        json=payload,
        timeout=15,
    )
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"send_mpnews 失败: {data}")


def send_summary_card(slug_data: list, overall_analysis: str, timestamp: str):
    """
    在所有 slug 详细报告前发送一条汇总消息。
    优先使用企业微信模板卡片（text_notice），条目超出上限或失败时降级为 Markdown。

    slug_data: [{"slug": ..., "question": ..., "yes_price": float|None,
                 "is_multi": bool, "sub_count": int,
                 "sub_options": [{"question":..., "yes_price":...}, ...]}, ...]
    overall_analysis : AI 整体解读文字
    timestamp        : 更新时间字符串，如 "2024-01-01 12:00 UTC"
    """
    def _price_str(yp) -> str:
        return f"{yp:.1%}" if yp is not None else "N/A"

    # ── 将 slug_data 展开为平铺的 (label, value) 列表 ──
    flat_items: list[tuple[str, str]] = []
    for d in slug_data:
        if d.get("is_multi") and d.get("sub_options"):
            for opt in d["sub_options"]:
                flat_items.append((opt["question"][:24], _price_str(opt.get("yes_price"))))
        else:
            flat_items.append((d["question"][:24], _price_str(d.get("yes_price"))))

    n_slugs = len(slug_data)

    # ── 尝试 template_card（展开后条目 ≤ 6 时）──
    if len(flat_items) <= _CARD_MAX_ITEMS:
        items = [{"keyname": label, "value": value} for label, value in flat_items]
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
                    "title": str(n_slugs),
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

    # ── 降级：Markdown，多选项展开为缩进子项 ──
    lines = ["## 📊 Polymarket 市场概览", f"> 更新时间：{timestamp}", ""]
    for d in slug_data:
        if d.get("is_multi") and d.get("sub_options"):
            lines.append(f"- **{d['question']}**")
            for opt in d["sub_options"]:
                lines.append(f"  - {opt['question']}：{_price_str(opt.get('yes_price'))}")
        else:
            lines.append(f"- **{d['question']}**：{_price_str(d.get('yes_price'))}")
        lines.append("")  # slug 之间的空行
    lines += ["**整体市场解读：**", overall_analysis]
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
