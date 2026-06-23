import time
import requests
import base64
import hashlib
from config import WECOM_WEBHOOK, CORP_ID, CORP_SECRET, AGENT_ID

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
    优先使用企业微信模板卡片（text_notice），条目超出上限或失败时降级为 Markdown。

    slug_data: [{"slug": ..., "question": ..., "yes_price": float|None,
                 "is_multi": bool, "sub_count": int,
                 "sub_options": [{"question":..., "yes_price":...}, ...]}, ...]
    timestamp : 更新时间字符串，如 "2024-01-01 12:00 UTC"
    """
    def _price_str(yp) -> str:
        return f"{yp:.1%}" if yp is not None else "N/A"

    def _expired_label(d: dict) -> str:
        """已过期 slug 在 value 字段的显示文本。"""
        reason = d.get("expired_reason") or "已过期"
        return f"⚠️ {reason}"

    # ── 将 slug_data 展开为平铺的 (label, value) 列表 ──
    # 注：template_card 的 keyname 字段企业微信侧有长度限制，保守截断到 30 字符。
    flat_items: list[tuple[str, str]] = []
    for d in slug_data:
        # 过期 slug 始终单独列一行，优先提示（不论单/多选项）
        if d.get("expired"):
            flat_items.append((d["question"][:30], _expired_label(d)))
            continue
        if d.get("is_multi") and d.get("sub_options"):
            for opt in d["sub_options"]:
                flat_items.append((opt["question"][:30], _price_str(opt.get("yes_price"))))
        else:
            flat_items.append((d["question"][:30], _price_str(d.get("yes_price"))))

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
                return
        except Exception:
            pass   # 降级到 Markdown

    # ── 降级：Markdown，每个市场独立区块 ──
    # 变化合并到一行（短期在前、趋势在后），|Δ|<0.5% 已在 report 层过滤；
    # 上涨红、下跌绿（见 report._format_changes）。每个字段自带 5d:/14d: 等
    # 时长标签，无需再前置"短期/趋势"二字。
    def _change_lines(fmt: dict | str) -> list[str]:
        if not isinstance(fmt, dict):
            return []
        parts = [s for s in (fmt.get("short"), fmt.get("long")) if s]
        if not parts:
            return []
        return [f"> {'  '.join(parts)}"]

    # 为避免超长时"按行"切分把单个市场拆到两条消息里（例如只剩
    # "5d:-3.0%  14d:-4.0%" 孤零零出现），把每个市场构建为独立的 section，
    # 统一由 _send_sections 按市场边界打包发送。
    preamble = ["## 📊 Polymarket 市场概览", f"> {timestamp}"]
    sections: list[list[str]] = []
    for d in slug_data:
        sec: list[str] = []
        # 过期 slug：先给出醒目提示，若仍有子选项/价格则附带最后快照
        if d.get("expired"):
            reason = d.get("expired_reason") or "已过期"
            sec.append(
                f'**{d["question"]}**：<font color="warning">⚠️ {reason}</font>'
            )
            if d.get("is_multi") and d.get("sub_options"):
                for opt in d["sub_options"]:
                    price = _price_str(opt.get("yes_price"))
                    sec.append(f"> {opt['question']}：**{price}**")
        elif d.get("is_multi") and d.get("sub_options"):
            sec.append(f"**{d['question']}**")
            for opt in d["sub_options"]:
                price = _price_str(opt.get("yes_price"))
                sec.append(f"> {opt['question']}：**{price}**")
                sec.extend(_change_lines(opt.get("changes_fmt")))
        else:
            price = _price_str(d.get("yes_price"))
            sec.append(f"**{d['question']}：{price}**")
            sec.extend(_change_lines(d.get("changes_fmt")))
        sections.append(sec)
    _send_sections(preamble, sections)


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


def _send_sections(preamble: list[str], sections: list[list[str]]) -> None:
    """
    按 section（单个市场）为最小单位打包发送 Markdown，保证：
      1. 单个市场永远不会被拆到两条消息里；
      2. 每条消息都带上 preamble（标题 + 时间戳），即便是续篇也有上下文；
      3. 贪心合并 sections 至接近 4096 字节上限。
    用于 send_summary_card，替代"按行盲切"的 send_long_markdown。
    """
    if not sections:
        send_markdown("\n".join(preamble))
        return

    header       = "\n".join(preamble)
    header_bytes = len(header.encode("utf-8")) + 2  # +2: 头与正文之间的空行

    buf: list[list[str]] = []
    used = header_bytes

    def _flush():
        nonlocal buf, used
        if not buf:
            return
        body = "\n\n".join("\n".join(s) for s in buf)
        send_markdown(f"{header}\n\n{body}")
        buf = []
        used = header_bytes

    for sec in sections:
        sec_bytes = len("\n".join(sec).encode("utf-8")) + 2  # +2: section 间空行
        # 单个 section 本身就超限的极端情况：单独一条发（仍好于被切碎）
        if sec_bytes + header_bytes > _MD_MAX_BYTES:
            _flush()
            send_markdown(f"{header}\n\n" + "\n".join(sec))
            continue
        if used + sec_bytes > _MD_MAX_BYTES and buf:
            _flush()
        buf.append(sec)
        used += sec_bytes

    _flush()


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


def _hormuz_trend_lines(trend: dict | None) -> list[str]:
    """构建"过去 24h 趋势"区块（基于累积快照）。无趋势数据时返回空列表。"""
    if not trend or trend.get("points", 0) < 1:
        return []
    pts = trend["points"]
    if pts < 2:
        # 仅 1 个数据点：尚无法比较，提示正在积累
        return ["", f"**📅 24h 趋势** <font color=\"comment\">数据积累中（已记录 {pts} 次）</font>"]

    span = trend.get("span_hours", 0) or 0
    out  = ["", f"**📅 24h 趋势**（{pts} 次采样 / 跨度约 {span:.0f}h）"]

    now   = trend.get("total_now", 0)
    parts = [f"在区船舶 {now}"]
    if trend.get("total_prev") is not None:
        parts.append(f"较上次 {now - trend['total_prev']:+d}")
    if trend.get("total_earliest") is not None:
        parts.append(f"较最早 {now - trend['total_earliest']:+d}")
    out.append("> " + "　".join(parts))
    out.append(
        f"> 区间 {trend.get('total_min', 0)} ~ {trend.get('total_max', 0)} 艘"
        f"　当前油轮 {trend.get('tankers_now', 0)}"
    )
    return out


def send_hormuz_card(stats: dict, analysis: str, timestamp: str, trend: dict | None = None):
    """
    发送霍尔木兹海峡实时通行态势 Markdown 卡片。
    stats    : hormuz.collect_hormuz_traffic() 的返回值
    analysis : analyzer.analyze_hormuz() 的中文研判（可为空串）
    timestamp: 更新时间字符串
    trend    : hormuz_history.summarize_trend() 的返回值（可为 None）
    """
    lines = ["## 🚢 霍尔木兹海峡通行实时跟踪", f"> {timestamp}"]

    # ── 数据源标识（vesselapi / aisstream）──
    source = (stats or {}).get("source", "aisstream")
    src_name, src_url = {
        "vesselapi": ("VesselAPI", "https://vesselapi.com/"),
        "aisstream": ("AISStream.io", "https://aisstream.io/"),
    }.get(source, ("AISStream.io", "https://aisstream.io/"))

    # ── 失败：给出明确提示 ──
    if not stats or not stats.get("ok"):
        reason = (stats or {}).get("error") or "未知错误"
        lines.append(f'> <font color="warning">⚠️ 通行数据采集失败：{reason}</font>')
        lines.append(f"> 数据来源：[{src_name}]({src_url})")
        send_long_markdown("\n".join(lines))
        return

    total  = stats.get("total", 0)
    frames = stats.get("msg_count", 0)
    area   = stats.get("area", "strait")
    if source == "vesselapi":
        meta = f"REST 快照 · 返回 {frames} 条"
    else:
        meta = f"采样 {stats.get('window_sec', 0)} 秒 · 收到 {frames} 帧"
    lines.append(f"> 数据来源：[{src_name}]({src_url})（AIS）· {meta}")

    # 海峡边界框无数据、已回退到大区时，明确标注数据范围
    if area == "wide":
        lines.append(
            '> <font color="comment">⚠️ 海峡主航道无数据，'
            '以下为「波斯湾—阿曼湾」大区探测结果。</font>'
        )

    if total == 0:
        if source == "vesselapi":
            hint = "未返回任何船舶（已含大区探测）。请检查 API Key / 配额，或该海域确无数据。"
        else:
            hint = ("采样窗口内未收到 AIS 报文（含大区覆盖探测）。多为 aisstream 在该海域"
                    "缺少岸基接收机覆盖；可尝试调大 HORMUZ_WINDOW_SEC，或更换为 VesselAPI。")
        lines.append(f'> <font color="comment">{hint}</font>')
        lines += _hormuz_trend_lines(trend)
        send_long_markdown("\n".join(lines))
        return

    moving   = stats.get("moving", 0)
    anchored = stats.get("anchored", 0)
    east     = stats.get("eastbound", 0)
    west     = stats.get("westbound", 0)
    avg_spd  = stats.get("avg_speed")

    lines.append("")
    lines.append(f"**在区船舶：{total} 艘**（航行中 {moving}，锚泊/停泊 {anchored}）")
    spd_txt = f"　平均航速 {avg_spd} 节" if avg_spd is not None else ""
    lines.append(
        f'> 东行（出湾·驶向阿曼湾）：<font color="info">{east}</font> 艘　'
        f'西行（入湾·驶入波斯湾）：<font color="warning">{west}</font> 艘{spd_txt}'
    )

    # ── 过去 24h 趋势（方案 B 累积）──
    lines += _hormuz_trend_lines(trend)

    # ── 船型构成 ──
    type_counts = stats.get("type_counts") or {}
    if type_counts:
        # 按数量降序，"未知"始终置末
        ordered = sorted(
            type_counts.items(),
            key=lambda kv: (kv[0] == "未知", -kv[1]),
        )
        breakdown = "　".join(f"{name} {cnt}" for name, cnt in ordered)
        lines.append("")
        lines.append("**船型构成**")
        lines.append(f"> {breakdown}")

    # ── 重点油轮动向 ──
    tankers = stats.get("tankers") or []
    if tankers:
        lines.append("")
        lines.append("**重点油轮动向**")
        dir_label = {"east": "东行", "west": "西行"}
        for t in tankers:
            parts = [f"🛢️ {t.get('name', '未知')}"]
            if t.get("direction"):
                parts.append(dir_label.get(t["direction"], ""))
            if t.get("sog") is not None:
                parts.append(f"{t['sog']:.1f}节")
            if t.get("destination"):
                parts.append(f"目的地 {t['destination']}")
            lines.append("> " + "｜".join(p for p in parts if p))

    # ── AI 研判 ──
    if analysis:
        lines.append("")
        lines.append(f"**📈 形势研判**\n> {analysis}")

    send_long_markdown("\n".join(lines))


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
