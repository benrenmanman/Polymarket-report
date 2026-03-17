import time
import requests
import base64
import hashlib
from config import WECOM_WEBHOOK, CORP_ID, CORP_SECRET, AGENT_ID

# template_card news_notice vertical_content_list 最多支持 4 条
_CARD_VERTICAL_MAX = 4
# template_card horizontal_content_list 最多支持 6 条
_CARD_MAX_ITEMS = 6

# 企业微信 Markdown 消息 UTF-8 字节数上限
_MD_MAX_BYTES = 4096

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


def send_summary_card(slug_data: list, timestamp: str):
    """
    在所有 slug 详细报告前发送一条汇总消息。
    优先使用企业微信 news_notice 模板卡片（vertical_content_list ≤ 4 条），
    超出或失败时降级为带颜色标注的 Markdown。

    slug_data: [{"slug": ..., "question": ..., "yes_price": float|None,
                 "is_multi": bool, "sub_count": int,
                 "sub_options": [{"question":..., "yes_price":...,
                                  "changes": {...}, "changes_str":...}], ...
                 "changes": {...}, "changes_str": ...}, ...]
    timestamp : 更新时间字符串，如 "2024-01-01 12:00 北京时间"
    """
    def _price_str(yp) -> str:
        return f"{yp:.1%}" if yp is not None else "N/A"

    def _short_chg(changes: dict) -> str:
        """仅取 1h / 1d 变化，作为卡片/Markdown 的简短标注。"""
        parts = []
        for key, label in [("1h", "1h"), ("1d", "1d")]:
            v = changes.get(key)
            if v is not None:
                parts.append(f"{label}{v:+.1%}")
        return "  ".join(parts)

    n_slugs = len(slug_data)

    # ── 展开为平铺的卡片条目列表 ──
    vert_items: list[dict] = []
    for d in slug_data:
        if d.get("is_multi") and d.get("sub_options"):
            for opt in d["sub_options"]:
                price     = _price_str(opt.get("yes_price"))
                chg_short = _short_chg(opt.get("changes", {}))
                desc      = f"YES {price}" + (f"　{chg_short}" if chg_short else "")
                vert_items.append({"title": opt["question"][:26], "desc": desc})
        else:
            price     = _price_str(d.get("yes_price"))
            chg_short = _short_chg(d.get("changes", {}))
            desc      = f"YES {price}" + (f"　{chg_short}" if chg_short else "")
            vert_items.append({"title": d["question"][:26], "desc": desc})

    # ── 尝试 news_notice 模板卡片（图文展示型，视觉更丰富）──
    if len(vert_items) <= _CARD_VERTICAL_MAX:
        payload = {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "news_notice",
                "source": {
                    "desc": "Polymarket 市场监控",
                    "desc_color": 0,
                },
                "main_title": {
                    "title": "📊 市场概览",
                    "desc": timestamp,
                },
                "vertical_content_list": vert_items,
                "horizontal_content_list": [
                    {"keyname": "监控市场", "value": f"{n_slugs} 个"},
                ],
                "jump_list": [
                    {
                        "type": 1,
                        "title": "前往 Polymarket",
                        "url": "https://polymarket.com",
                    }
                ],
                "card_action": {
                    "type": 1,
                    "url": "https://polymarket.com",
                },
            },
        }
        try:
            resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
            if resp.json().get("errcode", -1) == 0:
                return
        except Exception:
            pass  # 降级到 Markdown

    # ── 降级：Markdown，用企微颜色标签区分涨跌，布局更清晰 ──
    lines = [
        f"## 📊 Polymarket 市场概览",
        f"> 🕐 {timestamp}　共 **{n_slugs}** 个市场",
        "",
    ]
    for d in slug_data:
        if d.get("is_multi") and d.get("sub_options"):
            lines.append(f"**{d['question']}**")
            for opt in d["sub_options"]:
                price = _price_str(opt.get("yes_price"))
                chg   = opt.get("changes_str", "").strip()
                lines.append(f'> {opt["question"]}　<font color="info">{price}</font>')
                if chg:
                    lines.append(f'> <font color="comment">{chg}</font>')
        else:
            price = _price_str(d.get("yes_price"))
            chg   = d.get("changes_str", "").strip()
            yp    = d.get("yes_price")
            color = "info" if (yp is not None and yp >= 0.5) else "warning"
            lines.append(f'**{d["question"]}**　<font color="{color}">{price}</font>')
            if chg:
                lines.append(f'> <font color="comment">{chg}</font>')
        lines.append("")  # 市场间空行
    send_long_markdown("\n".join(lines))


def send_text(content: str):
    """原有函数，保持不变"""
    payload = {"msgtype": "text", "text": {"content": content}}
    resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
    data = resp.json()
    if data.get("errcode", 0) != 0:
        print(f"[notifier] send_text 失败: {data}")


def send_markdown(content: str):
    """原有函数（如有），保持不变"""
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"send_markdown 失败: {data}")


def send_long_markdown(content: str) -> None:
    """
    发送可能超长的 Markdown 消息。
    企微限制为 4096 字节（UTF-8），中文字符每个占 3 字节。
    若内容超限，按行切割为多段依次发送。
    """
    if len(content.encode("utf-8")) <= _MD_MAX_BYTES:
        send_markdown(content)
        return
    lines = content.split("\n")
    chunk: list[str] = []
    chunk_bytes = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for \n
        if chunk_bytes + line_bytes > _MD_MAX_BYTES and chunk:
            send_markdown("\n".join(chunk))
            chunk = []
            chunk_bytes = 0
        chunk.append(line)
        chunk_bytes += line_bytes
    if chunk:
        send_markdown("\n".join(chunk))


# 企业微信 webhook 图片大小限制
_IMAGE_MAX_BYTES = 2 * 1024 * 1024   # 2 MB


def send_image(image_bytes: bytes):
    """
    新增：发送图片到企业微信。
    image_bytes : PNG/JPG 的原始字节（由 analyzer.plot_highfreq 返回）
    超过 2MB 或企微返回错误码时抛出 RuntimeError，供调用方触发降级逻辑。
    """
    if not image_bytes:
        return
    if len(image_bytes) > _IMAGE_MAX_BYTES:
        raise RuntimeError(
            f"图片大小 {len(image_bytes) / 1024:.0f} KB 超出企业微信 2 MB 限制"
        )
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
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"send_image 失败: {data}")


def send_highfreq_report(question: str, analysis: str, chart_bytes: bytes):
    """
    组合发送高频报告（文字 + 图片）。
    question    : 市场问题文本
    analysis    : analyze_highfreq() 返回的 AI 解读文字
    chart_bytes : plot_highfreq() 返回的 PNG bytes
    """
    # 1. 文字解读：标题加粗 + 分隔线引导 + 正文
    md = "\n".join([
        f"**📈 {question}**",
        "",
        analysis,
        "",
        '<font color="comment">—— 走势图见下方 ——</font>',
    ])
    send_markdown(md)

    # 2. 走势图
    if chart_bytes:
        send_image(chart_bytes)
