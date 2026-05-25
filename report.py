import json
import re
import pandas as pd
from datetime import datetime, timezone, timedelta
from history import fetch_highfreq
from fetcher import fetch_market, fetch_market_with_meta, check_market_expired
from analyzer import (
    analyze_snapshot,
    translate_to_chinese,
    translate_sub_options_short,
    summarize_highfreq,
    analyze_highfreq,
    plot_highfreq,
    plot_all_highfreq_combined,
)
from notifier import (
    send_text,
    send_highfreq_report,
    send_summary_card,
    upload_image_for_mpnews,
    upload_media_thumb,
    send_mpnews,
)
from config import SLUGS, MPNEWS_ENABLED


# ──────────────────────────────────────────
# 内部工具：从市场 dict 提取 token_id
# ──────────────────────────────────────────
def _extract_yes_price(market: dict) -> float | None:
    """从市场 dict 提取 YES（第一项）当前概率，无法解析时返回 None"""
    prices = market.get("outcomePrices", "[]")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            return None
    try:
        return float(prices[0]) if prices else None
    except (ValueError, TypeError):
        return None


def _extract_token_id(market: dict) -> str | None:
    token_ids = market.get("clobTokenIds", [])
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    return token_ids[0] if token_ids else None


def _compute_price_changes(df_1min, df_1day) -> dict:
    """
    从 1min（近1天）和 1day（近30天）df 中，计算当前价格与
    5分/30分/1时/1日/3日/5日/14日 前的差值。不可用时值为 None。
    """
    def _lookup(df, delta):
        if df is None or df.empty:
            return None
        now    = df["datetime"].max()
        target = now - delta
        if target < df["datetime"].min():
            return None
        return df.loc[(df["datetime"] - target).abs().idxmin(), "price"]

    current = None
    if df_1min is not None and not df_1min.empty:
        current = float(df_1min["price"].iloc[-1])
    elif df_1day is not None and not df_1day.empty:
        current = float(df_1day["price"].iloc[-1])
    if current is None:
        return {"5m": None, "30m": None, "1h": None, "1d": None, "3d": None, "5d": None, "14d": None}

    p5m  = _lookup(df_1min, pd.Timedelta(minutes=5))
    p30m = _lookup(df_1min, pd.Timedelta(minutes=30))
    p1h  = _lookup(df_1min, pd.Timedelta(hours=1))
    p1d  = _lookup(df_1day, pd.Timedelta(days=1))
    p3d  = _lookup(df_1day, pd.Timedelta(days=3))
    p5d  = _lookup(df_1day, pd.Timedelta(days=5))
    p14d = _lookup(df_1day, pd.Timedelta(days=14))

    return {
        "5m":  (current - p5m)  if p5m  is not None else None,
        "30m": (current - p30m) if p30m is not None else None,
        "1h":  (current - p1h)  if p1h  is not None else None,
        "1d":  (current - p1d)  if p1d  is not None else None,
        "3d":  (current - p3d)  if p3d  is not None else None,
        "5d":  (current - p5d)  if p5d  is not None else None,
        "14d": (current - p14d) if p14d is not None else None,
    }


# |Δ| 低于此阈值视为"基本无变化"，直接省略，避免噪音。
_CHANGE_THRESHOLD = 0.005  # 0.5%


def _format_changes(changes: dict) -> dict:
    """
    将变化字典格式化为两行彩色 Markdown 字符串：短期（5m/30m/1h）和中长期
    （1d/3d/5d/14d）。|Δ| < 0.5% 的字段直接省略。上涨用 warning（橙红），
    下跌用 info（绿），符合 A 股颜色直觉。

    返回 {"short": str, "long": str}，任一行可能为空串。
    """
    def _one(key, label):
        v = changes.get(key)
        if v is None or abs(v) < _CHANGE_THRESHOLD:
            return None
        # 涨：红（#ff0000）；跌：info（绿）。沿用 A 股直觉配色。
        color = "#ff0000" if v > 0 else "info"
        return f'<font color="{color}">{label}:{v:+.1%}</font>'

    short_parts = [p for p in (_one(k, l) for k, l in [("5m", "5m"), ("30m", "30m")]) if p]
    long_parts  = [p for p in (_one(k, l) for k, l in [("1d", "1d"), ("5d", "5d"), ("14d", "14d")]) if p]

    return {
        "short": "  ".join(short_parts),
        "long":  "  ".join(long_parts),
    }


# 多选项市场主标题中冗余的时间限定短语（子选项已各自携带日期）
# 按最长优先排序，避免部分匹配留下孤立的年份/月份
# 前缀 "会?在?" 一并吸收，替换为 "何时" 后读作 "……何时……"
_MULTI_TITLE_DATE_RE = re.compile(
    r'会?在?\d{4}年\d+月\d+日(?:之)?前|'  # 会在2025年12月31日之前
    r'会?在?\d{4}年\d+月(?:底)?(?:之)?前|'  # 会在2025年12月底前
    r'会?在?\d+月\d+日(?:之)?前|'         # 会在12月31日前 / 4月30日前
    r'会?在?\d+月(?:底)?(?:之)?前|'       # 会在4月底前
    r'会?在?\d{4}年(?:底)?(?:之)?前|'     # 会在2027年前 / 2026年底前
    r'会?在?今年(?:底)?(?:之)?前'         # 会在今年底前
)


def _rewrite_multi_title(text: str) -> str:
    """将多选项市场主标题中的时间限定短语替换为"何时"；仅在发生替换时把句末"吗？"改为"？"。"""
    rewritten, n = _MULTI_TITLE_DATE_RE.subn('何时', text)
    rewritten = re.sub(r'\s+', '', rewritten).strip()
    if n > 0:
        if rewritten.endswith('吗？'):
            rewritten = rewritten[:-2] + '？'
        elif rewritten.endswith('吗?'):
            rewritten = rewritten[:-2] + '?'
    return rewritten


# Polymarket 部分 event.title 含字面 "..." 占位符（如
# "Will US and Iran reach a permanent peace deal by ...?"），
# 翻译后会出现 "能否在……之前" 等是非问句加占位短语，整体改写为"何时"。
_TITLE_ELLIPSIS_RE = re.compile(r'(?:能否|会否|是否)?(?:在)?(?:……|\.{3,}|…)(?:之前|前)?')


def _clean_event_title(text: str) -> str:
    """把 event.title 翻译后的"能否在……之前"占位短语改写为"何时"，并归一化句末。"""
    cleaned, n = _TITLE_ELLIPSIS_RE.subn('何时', text)
    if n == 0:
        return text
    cleaned = re.sub(r'\s+', '', cleaned).strip()
    if cleaned.endswith('吗？'):
        cleaned = cleaned[:-2] + '？'
    elif cleaned.endswith('吗?'):
        cleaned = cleaned[:-2] + '?'
    elif cleaned and not cleaned.endswith(('？', '?')):
        cleaned += '？'
    return cleaned or text


def _apply_translations(slug_data: list) -> None:
    """
    两步翻译 slug_data 中的所有英文文本：
    1. 批量翻译主 question（一次 AI 调用）；多选项市场的主标题
       把日期限定短语改写为"何时"（子选项已各自携带日期）
    2. 对每个多选项市场，以已译的主问题为上下文，
       翻译 sub_options 为简短标签（每组一次 AI 调用）
    """
    # ── 第一步：翻译主问题（多选项市场同步改写日期为"何时"） ──
    # use_event_title=True 时主标题来自 Polymarket 官方 event.title，
    # 已是泛化的多选项问法（如"特朗普会在5月31日前同意伊朗的哪些要求？"），
    # 不再做"日期→何时"改写，保留与网站一致的呈现。
    main_texts = [d["question"] for d in slug_data]
    main_translated = translate_to_chinese(main_texts)
    for d, trans in zip(slug_data, main_translated):
        if d.get("is_multi"):
            if d.get("use_event_title"):
                trans = _clean_event_title(trans)
            else:
                trans = _rewrite_multi_title(trans) or trans
        d["question"] = trans

    # ── 第二步：翻译各多选项的子选项（短标签） ──
    for d in slug_data:
        if not d.get("sub_options"):
            continue
        sub_texts = [opt["question"] for opt in d["sub_options"]]
        sub_translated = translate_sub_options_short(d["question"], sub_texts)
        for opt, trans in zip(d["sub_options"], sub_translated):
            opt["question"] = trans


# 子选项标签里的日期 / 加息次数模式，用于识别多选项市场的类型
_OPT_DATE_RE  = re.compile(r'\d+月\d+日')
_OPT_COUNT_RE = re.compile(r'^\s*\d+\s*次')


def _limit_display_sub_options(slug_data: list) -> None:
    """
    按市场类型精简多选项市场展示的子选项数量（在过滤/排序之后调用）：
      · 「……哪个政党掌控？」：只保留概率最高的那个政党（top 1）
      · 总统大选「胜出者/胜者是谁」：按概率降序取前 3 名候选人
      · 「……降息几次？」     ：保留前 3 个（即 0/1/2 次）
      · 多日期市场           ：按日期升序后只保留最早的 3 个日期
    其余多选项市场（如"会同意哪些要求"）保持原样，全部展示。
    """
    for d in slug_data:
        if not d.get("is_multi"):
            continue
        subs = d.get("sub_options") or []
        if not subs:
            continue
        q = d.get("question", "")

        def _by_prob_desc(options):
            return sorted(options, key=lambda o: o.get("yes_price") or 0.0, reverse=True)

        if "政党" in q or all("党" in o.get("question", "") for o in subs):
            subs = _by_prob_desc(subs)[:1]
        elif any(k in q for k in ("胜", "大选", "当选", "谁")):
            subs = _by_prob_desc(subs)[:3]
        elif "几次" in q or all(_OPT_COUNT_RE.search(o.get("question", "")) for o in subs):
            subs = subs[:3]
        elif sum(1 for o in subs if _OPT_DATE_RE.search(o.get("question", ""))) >= 2:
            subs = subs[:3]

        d["sub_options"] = subs
        d["sub_count"]   = len(subs)


def _filter_and_sort_sub_options(slug_data: list) -> None:
    """
    过滤已过期（月/日早于今日）的子选项，再按日期升序排序。
    对跨年场景（今日距该日期 > 180 天）视为明年到期，保留。
    排序完成后再按市场类型精简展示条目（见 _limit_display_sub_options）。
    """
    beijing_tz = timezone(timedelta(hours=8))
    today      = datetime.now(beijing_tz)

    def _parse_date(opt):
        m = re.search(r'(\d+)月(\d+)日', opt.get("question", ""))
        return (int(m.group(1)), int(m.group(2))) if m else None

    def _is_past_due(opt) -> bool:
        date = _parse_date(opt)
        if date is None:
            return False
        try:
            candidate = datetime(today.year, date[0], date[1], tzinfo=today.tzinfo)
        except ValueError:
            return False
        days_delta = (candidate.date() - today.date()).days
        if days_delta >= 0:
            return False
        # 落在过去且差距 > 180 天时，视为明年到期（跨年），保留
        return days_delta >= -180

    for d in slug_data:
        if not d.get("sub_options"):
            continue
        d["sub_options"] = [o for o in d["sub_options"] if not _is_past_due(o)]
        d["sub_options"].sort(key=lambda o: _parse_date(o) or (99, 99))
        d["sub_count"]   = len(d["sub_options"])

    _limit_display_sub_options(slug_data)


# ──────────────────────────────────────────
# 内部：对单个子市场发送高频报告
# ──────────────────────────────────────────
def _run_single_highfreq(question: str, token_id: str, mode: str):
    df = fetch_highfreq(token_id, mode=mode)
    if df.empty:
        send_text(f"⚠️ [{question}] mode={mode} 未获取到高频数据")
        return

    summary     = summarize_highfreq(df, mode=mode)
    analysis    = analyze_highfreq(question, summary)
    chart_bytes = plot_highfreq(df, question, mode=mode)
    send_highfreq_report(question, analysis, chart_bytes)
    print(f"[report] 高频报告已发送: {question} ({mode})")


# ──────────────────────────────────────────
# 所有 slug 结果汇总（在详细报告前发送）
# ──────────────────────────────────────────
def run_slugs_summary(slugs: list):
    """
    汇总所有 slug 的当前快照价格，调用 AI 生成整体解读，
    并通过企业微信发送一条汇总消息（template_card 或 Markdown）。
    """
    beijing_tz = timezone(timedelta(hours=8))
    timestamp  = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M 北京时间")
    slug_data  = []

    for slug in slugs:
        try:
            meta = fetch_market_with_meta(slug)
            market = meta["data"]
            if market is None:
                slug_data.append({
                    "slug":           slug,
                    "question":       slug,
                    "yes_price":      None,
                    "is_multi":       False,
                    "sub_count":      0,
                    "sub_options":    [],
                    "expired":        True,
                    "expired_reason": meta["reason"],
                })
                continue

            if isinstance(market, list):
                m           = market[0]
                is_multi    = True
                sub_cnt     = len(market)
                # 优先使用 Polymarket 的 groupItemTitle 短标签（与网站一致），
                # 缺失时回落到完整 question。
                sub_options = [
                    {
                        "question":  sub.get("groupItemTitle") or sub.get("question", ""),
                        "yes_price": _extract_yes_price(sub),
                    }
                    for sub in market
                ]
                # 多选项市场主标题优先使用 event.title（与网站一致），
                # 缺失时回落到第一个子市场的 question。
                main_question = meta.get("event_title") or m.get("question", slug)
                use_event_title = bool(meta.get("event_title"))
            else:
                m               = market
                is_multi        = False
                sub_cnt         = 1
                sub_options     = []
                main_question   = m.get("question", slug)
                use_event_title = False

            slug_data.append({
                "slug":             slug,
                "question":         main_question,
                "yes_price":        _extract_yes_price(m),
                "is_multi":         is_multi,
                "sub_count":        sub_cnt,
                "sub_options":      sub_options,
                "expired":          meta["expired"],
                "expired_reason":   meta["reason"],
                "use_event_title":  use_event_title,
            })
        except Exception as e:
            print(f"[report] 汇总: {slug} 获取失败: {e}")
            slug_data.append({
                "slug":           slug,
                "question":       slug,
                "yes_price":      None,
                "is_multi":       False,
                "sub_count":      0,
                "sub_options":    [],
                "expired":        True,
                "expired_reason": "slug 未找到",
            })

    try:
        _apply_translations(slug_data)
    except Exception as e:
        print(f"[report] 翻译失败，使用原文: {e}")

    _filter_and_sort_sub_options(slug_data)
    send_summary_card(slug_data, timestamp)
    print(f"[report] 汇总消息已发送，共 {len(slug_data)} 个市场")


# ──────────────────────────────────────────
# 快照报告
# ──────────────────────────────────────────
def run_report(slug: str):
    market = fetch_market(slug)
    if not market:
        send_text(f"[{slug}] 无法获取市场数据")
        return
    # 多选项市场取第一个子市场做快照
    m = market[0] if isinstance(market, list) else market
    analysis = analyze_snapshot(m)
    send_text(f"📌 {slug}\n{analysis}")


# ──────────────────────────────────────────
# 高频数据报告（自动兼容单/多选项市场）
# ──────────────────────────────────────────
def run_highfreq_report(slug: str, mode: str = "1min"):
    print(f"[report] 开始高频报告: slug={slug}, mode={mode}")

    market = fetch_market(slug)   # dict（单市场）或 list（多选项市场）

    if isinstance(market, list):
        # ── 多选项市场：逐个子市场发送 ──
        print(f"[report] 多选项市场，共 {len(market)} 个选项")
        for sub in market:
            question = sub.get("question", slug)
            token_id = _extract_token_id(sub)
            if not token_id:
                print(f"[report] 跳过无 token_id 的子市场: {question}")
                continue
            try:
                _run_single_highfreq(question, token_id, mode)
            except Exception as e:
                send_text(f"❌ [{question}] mode={mode} 子市场报告失败: {e}")
                print(f"[report] 子市场错误: {e}")
    else:
        # ── 单市场 ──
        question = market.get("question", slug)
        token_id = _extract_token_id(market)
        if not token_id:
            send_text(f"⚠️ [{slug}] 无法获取 token_id")
            return
        _run_single_highfreq(question, token_id, mode)


# ──────────────────────────────────────────
# 降级路径：一次性拉取快照 + 高频数据，计算价格变化
# ──────────────────────────────────────────
def _build_all_data(slugs: list) -> tuple:
    """
    一次遍历，同时构建：
      slug_data  : 概览列表（含 changes_fmt 字段）
      all_entries: 高频列表（含 df、chart，供合并长图）
    返回 (slug_data, all_entries)
    """
    slug_data   = []
    all_entries = []

    for slug in slugs:
        try:
            meta = fetch_market_with_meta(slug)
            market = meta["data"]
            if market is None:
                slug_data.append({
                    "slug": slug, "question": slug, "yes_price": None,
                    "is_multi": False, "sub_count": 0, "sub_options": [],
                    "changes": {}, "changes_fmt": {"short": "", "long": ""},
                    "expired": True, "expired_reason": meta["reason"],
                })
                continue

            sub_markets = market if isinstance(market, list) else [market]
            is_multi    = isinstance(market, list)

            slug_expired        = meta["expired"]
            slug_expired_reason = meta["reason"]

            sub_options_out = []

            for sub in sub_markets:
                full_question = sub.get("question", slug)
                # 多选项：用 groupItemTitle 作为简短标签（与网站一致）；
                # 单市场：question 本身就是完整问题，沿用。
                short_label   = (sub.get("groupItemTitle") or full_question) if is_multi else full_question
                token_id      = _extract_token_id(sub)
                yes_price     = _extract_yes_price(sub)

                df_1min  = pd.DataFrame()
                df_1day = pd.DataFrame()
                entry    = {"slug": slug, "question": short_label, "modes": {}}

                if token_id:
                    for mode in ["1min", "1day"]:
                        try:
                            df = fetch_highfreq(token_id, mode=mode)
                            if not df.empty:
                                chart = plot_highfreq(df, short_label, mode=mode)
                                entry["modes"][mode] = {"df": df, "chart": chart}
                                if mode == "1min":
                                    df_1min = df
                                else:
                                    df_1day = df
                        except Exception as e:
                            print(f"[report] {short_label} {mode} 失败: {e}")

                all_entries.append(entry)

                changes = _compute_price_changes(
                    df_1min  if not df_1min.empty  else None,
                    df_1day if not df_1day.empty else None,
                )
                sub_options_out.append({
                    "question":    short_label,
                    "yes_price":   yes_price,
                    "changes":     changes,
                    "changes_fmt": _format_changes(changes),
                })

            m = sub_markets[0]
            top = sub_options_out[0] if sub_options_out else {}
            # 多选项市场主标题优先 event.title；单市场用自身 question。
            if is_multi:
                main_question   = meta.get("event_title") or m.get("question", slug)
                use_event_title = bool(meta.get("event_title"))
            else:
                main_question   = m.get("question", slug)
                use_event_title = False
            slug_data.append({
                "slug":             slug,
                "question":         main_question,
                "yes_price":        _extract_yes_price(m),
                "is_multi":         is_multi,
                "sub_count":        len(sub_markets),
                "sub_options":      sub_options_out if is_multi else [],
                "changes":          top.get("changes", {}),
                "changes_fmt":      top.get("changes_fmt", {"short": "", "long": ""}),
                "expired":          slug_expired,
                "expired_reason":   slug_expired_reason,
                "use_event_title":  use_event_title,
            })

        except Exception as e:
            print(f"[report] _build_all_data: {slug} 失败: {e}")
            slug_data.append({
                "slug": slug, "question": slug, "yes_price": None,
                "is_multi": False, "sub_count": 0, "sub_options": [],
                "changes": {}, "changes_fmt": {"short": "", "long": ""},
                "expired": True, "expired_reason": "slug 未找到",
            })

    return slug_data, all_entries


# ──────────────────────────────────────────
# mpnews：收集全量数据（不发消息）
# ──────────────────────────────────────────
def _collect_all_highfreq_data(slugs: list) -> list:
    """
    遍历所有 slug，拉取双粒度高频数据，返回结构化列表供 mpnews 使用。
    每个元素：{"slug": ..., "question": ..., "modes": {"1min": {...}, "1day": {...}}}
    modes[mode] 包含 summary / analysis / chart(bytes)
    """
    all_entries = []
    for slug in slugs:
        try:
            market = fetch_market(slug)
            sub_markets = market if isinstance(market, list) else [market]
            for sub in sub_markets:
                question = sub.get("question", slug)
                token_id = _extract_token_id(sub)
                if not token_id:
                    continue
                entry = {"slug": slug, "question": question, "modes": {}}
                for mode in ["1min", "1day"]:
                    df = fetch_highfreq(token_id, mode=mode)
                    if df.empty:
                        continue
                    summary  = summarize_highfreq(df, mode=mode)
                    analysis = analyze_highfreq(question, summary)
                    chart    = plot_highfreq(df, question, mode=mode)
                    entry["modes"][mode] = {
                        "summary":  summary,
                        "analysis": analysis,
                        "chart":    chart,
                        "df":       df,      # 供合并长图使用
                    }
                all_entries.append(entry)
        except Exception as e:
            print(f"[report] _collect: {slug} 失败: {e}")
    return all_entries


# ──────────────────────────────────────────
# mpnews：构建 HTML 并一次性发送图文消息
# ──────────────────────────────────────────
def build_and_send_mpnews_report(slugs: list):
    """
    将所有 slug 的汇总 + 详细分析 + 走势图打包成一篇企业微信图文消息（mpnews）发送。
    依赖 CORP_ID / CORP_SECRET / AGENT_ID 配置。
    """
    beijing_tz = timezone(timedelta(hours=8))
    timestamp  = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M 北京时间")

    # ── 1. 快照汇总 & AI 整体解读 ──
    slug_data = []
    for slug in slugs:
        try:
            meta = fetch_market_with_meta(slug)
            market = meta["data"]
            if market is None:
                slug_data.append({
                    "slug":           slug,
                    "question":       slug,
                    "yes_price":      None,
                    "is_multi":       False,
                    "sub_count":      0,
                    "sub_options":    [],
                    "expired":        True,
                    "expired_reason": meta["reason"],
                })
                continue

            if isinstance(market, list):
                m           = market[0]
                is_multi    = True
                sub_cnt     = len(market)
                sub_options = [
                    {
                        "question":  sub.get("groupItemTitle") or sub.get("question", ""),
                        "yes_price": _extract_yes_price(sub),
                    }
                    for sub in market
                ]
                main_question   = meta.get("event_title") or m.get("question", slug)
                use_event_title = bool(meta.get("event_title"))
            else:
                m               = market
                is_multi        = False
                sub_cnt         = 1
                sub_options     = []
                main_question   = m.get("question", slug)
                use_event_title = False
            slug_data.append({
                "slug":             slug,
                "question":         main_question,
                "yes_price":        _extract_yes_price(m),
                "is_multi":         is_multi,
                "sub_count":        sub_cnt,
                "sub_options":      sub_options,
                "use_event_title":  use_event_title,
                "expired":        meta["expired"],
                "expired_reason": meta["reason"],
            })
        except Exception as e:
            print(f"[report] mpnews 快照: {slug} 失败: {e}")
            slug_data.append({
                "slug":           slug,
                "question":       slug,
                "yes_price":      None,
                "is_multi":       False,
                "sub_count":      0,
                "sub_options":    [],
                "expired":        True,
                "expired_reason": "slug 未找到",
            })

    try:
        _apply_translations(slug_data)
    except Exception as e:
        print(f"[report] 翻译失败，使用原文: {e}")

    _filter_and_sort_sub_options(slug_data)

    # ── 2. 收集详细高频数据 ──
    all_entries = _collect_all_highfreq_data(slugs)

    # ── 3. 构建 HTML 文章内容 ──
    def _price_str(d: dict) -> str:
        if d.get("is_multi"):
            return f"多选项（{d.get('sub_count', 0)} 个选项）"
        yp = d.get("yes_price")
        return f"{yp:.1%}" if yp is not None else "N/A"

    def _expired_badge(d: dict) -> str:
        if not d.get("expired"):
            return ""
        reason = d.get("expired_reason") or "已过期"
        return f' <span style="color:#d9534f">⚠️ {reason}</span>'

    html_parts = [
        f"<h2>📊 Polymarket 市场报告</h2>",
        f"<p><b>更新时间：</b>{timestamp}</p>",
        "<h3>市场概览</h3>",
        "<table border='1' cellpadding='6' cellspacing='0'>",
        "<tr><th>市场</th><th>当前概率（YES）</th></tr>",
    ]
    for d in slug_data:
        badge = _expired_badge(d)
        if d.get("is_multi") and d.get("sub_options"):
            # 多选项市场：展开每个子选项
            def _opt_price(yp) -> str:
                return f"{yp:.1%}" if yp is not None else "N/A"
            sub_rows = "".join(
                f"<li>{opt['question']}：{_opt_price(opt.get('yes_price'))}</li>"
                for opt in d["sub_options"]
            )
            html_parts.append(
                f"<tr><td>{d['question']}{badge}<ul>{sub_rows}</ul></td><td>—</td></tr>"
            )
        else:
            html_parts.append(
                f"<tr><td>{d['question']}{badge}</td><td>{_price_str(d)}</td></tr>"
            )
    html_parts += [
        "</table>",
        "<hr/>",
        "<h3>详细走势分析</h3>",
    ]

    # ── 4. 上传图片并嵌入 HTML ──
    thumb_media_id: str | None = None
    for entry in all_entries:
        html_parts.append(f"<h4>{entry['question']}</h4>")
        for mode in ["1min", "1day"]:
            data = entry["modes"].get(mode)
            if not data:
                continue
            mode_label = "近1天（1分钟粒度）" if mode == "1min" else "近30天（1小时粒度）"
            html_parts.append(f"<p><b>{mode_label}：</b>{data['analysis']}</p>")
            if data["chart"]:
                try:
                    img_url = upload_image_for_mpnews(data["chart"])
                    html_parts.append(
                        f'<img src="{img_url}" style="max-width:100%;height:auto"/>'
                    )
                    if thumb_media_id is None:
                        thumb_media_id = upload_media_thumb(data["chart"])
                except Exception as e:
                    print(f"[report] 图片上传失败 ({entry['question']} {mode}): {e}")

    if thumb_media_id is None:
        raise RuntimeError("所有图表均上传失败，无法生成 mpnews 缩略图")

    html = "\n".join(html_parts)

    # ── 5. 发送 mpnews ──
    articles = [{
        "title":          f"Polymarket 市场报告 · {timestamp}",
        "thumb_media_id": thumb_media_id,
        "author":         "Polymarket Bot",
        "content":        html,
        "digest":         f"共 {len(slug_data)} 个市场 · {timestamp}",
    }]
    send_mpnews(articles)
    print(f"[report] mpnews 图文报告已发送，共 {len(slug_data)} 个市场")


# ──────────────────────────────────────────
# 批量发送多个 slug 的双粒度报告
# ──────────────────────────────────────────
def run_all_highfreq_reports(slugs: list):
    # ── 优先：mpnews 一体化图文（需配置应用 API 凭据）──
    if MPNEWS_ENABLED:
        try:
            build_and_send_mpnews_report(slugs)
            return
        except Exception as e:
            send_text(f"⚠️ mpnews 发送失败，已降级为分段消息: {e}")
            print(f"[report] mpnews 失败，降级: {e}")

    # ── 降级：一次拉取所有数据，发概览卡片 + 合并长图（不发文字分析）──
    beijing_tz = timezone(timedelta(hours=8))
    timestamp  = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M 北京时间")

    slug_data, all_entries = _build_all_data(slugs)

    # ── 翻译，并同步更新 all_entries 里的 question 字段 ──
    try:
        # 翻译前记录原始文本，用于事后建立映射
        pre_main = [d["question"] for d in slug_data]
        pre_subs = [
            [opt["question"] for opt in d.get("sub_options", [])]
            for d in slug_data
        ]
        _apply_translations(slug_data)
        # 建立 原文 -> 译文 的查找表
        trans_map: dict[str, str] = {}
        for i, d in enumerate(slug_data):
            trans_map[pre_main[i]] = d["question"]
            for j, opt in enumerate(d.get("sub_options", [])):
                if j < len(pre_subs[i]):
                    trans_map[pre_subs[i][j]] = opt["question"]
        # 将译文同步写入 all_entries（供 plot_all_highfreq_combined 使用）
        for entry in all_entries:
            entry["question"] = trans_map.get(entry["question"], entry["question"])
    except Exception as e:
        print(f"[report] 翻译失败，使用原文: {e}")

    _filter_and_sort_sub_options(slug_data)

    try:
        send_summary_card(slug_data, timestamp)
        print(f"[report] 汇总消息已发送，共 {len(slug_data)} 个市场")
    except Exception as e:
        send_text(f"⚠️ 汇总消息发送失败: {e}")
        print(f"[report] 汇总失败: {e}")


# ──────────────────────────────────────────
# 入口
# ──────────────────────────────────────────
if __name__ == "__main__":
    run_all_highfreq_reports(SLUGS)
