import json
import pandas as pd
from datetime import datetime, timezone, timedelta
from history import fetch_highfreq
from fetcher import fetch_market
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
    5分/30分/1时/5日/14日 前的差值。不可用时值为 None。
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
        return {"5m": None, "30m": None, "1h": None, "5d": None, "14d": None}

    p5m  = _lookup(df_1min, pd.Timedelta(minutes=5))
    p30m = _lookup(df_1min, pd.Timedelta(minutes=30))
    p1h  = _lookup(df_1min, pd.Timedelta(hours=1))
    p5d  = _lookup(df_1day, pd.Timedelta(days=5))
    p14d = _lookup(df_1day, pd.Timedelta(days=14))

    return {
        "5m":  (current - p5m)  if p5m  is not None else None,
        "30m": (current - p30m) if p30m is not None else None,
        "1h":  (current - p1h)  if p1h  is not None else None,
        "5d":  (current - p5d)  if p5d  is not None else None,
        "14d": (current - p14d) if p14d is not None else None,
    }


def _format_changes(changes: dict) -> str:
    """将变化字典格式化为带颜色的 Markdown 片段：正值红色，负值绿色。"""
    def _one(key, label):
        v = changes.get(key)
        if v is None:
            return f"{label}:n/a"
        color = "#FF0000" if v >= 0 else "#00AA00"
        return f'{label}:<font color="{color}">{v:+.1%}</font>'

    parts = [_one(k, l) for k, l in [("5m", "5m"), ("30m", "30m"), ("1h", "1h"), ("5d", "5d"), ("14d", "14d")]]
    return "  ".join(parts)


def _apply_translations(slug_data: list) -> None:
    """
    两步翻译 slug_data 中的所有英文文本：
    1. 批量翻译主 question（一次 AI 调用）
    2. 对每个多选项市场，以已译的主问题为上下文，
       翻译 sub_options 为简短标签（每组一次 AI 调用）
    """
    # ── 第一步：翻译主问题 ──
    main_texts = [d["question"] for d in slug_data]
    main_translated = translate_to_chinese(main_texts)
    for d, trans in zip(slug_data, main_translated):
        d["question"] = trans

    # ── 第二步：翻译各多选项的子选项（短标签） ──
    for d in slug_data:
        if not d.get("sub_options"):
            continue
        sub_texts = [opt["question"] for opt in d["sub_options"]]
        sub_translated = translate_sub_options_short(d["question"], sub_texts)
        for opt, trans in zip(d["sub_options"], sub_translated):
            opt["question"] = trans


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
            market = fetch_market(slug)
            if isinstance(market, list):
                m           = market[0]
                is_multi    = True
                sub_cnt     = len(market)
                sub_options = [
                    {
                        "question":  sub.get("question", ""),
                        "yes_price": _extract_yes_price(sub),
                    }
                    for sub in market
                ]
            else:
                m           = market
                is_multi    = False
                sub_cnt     = 1
                sub_options = []

            slug_data.append({
                "slug":        slug,
                "question":    m.get("question", slug),
                "yes_price":   _extract_yes_price(m),
                "is_multi":    is_multi,
                "sub_count":   sub_cnt,
                "sub_options": sub_options,
            })
        except Exception as e:
            print(f"[report] 汇总: {slug} 获取失败: {e}")
            slug_data.append({
                "slug":        slug,
                "question":    slug,
                "yes_price":   None,
                "is_multi":    False,
                "sub_count":   0,
                "sub_options": [],
            })

    try:
        _apply_translations(slug_data)
    except Exception as e:
        print(f"[report] 翻译失败，使用原文: {e}")

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
      slug_data  : 概览列表（含 changes_str 字段）
      all_entries: 高频列表（含 df、chart，供合并长图）
    返回 (slug_data, all_entries)
    """
    slug_data   = []
    all_entries = []

    for slug in slugs:
        try:
            market     = fetch_market(slug)
            sub_markets = market if isinstance(market, list) else [market]
            is_multi    = isinstance(market, list)

            sub_options_out = []

            for sub in sub_markets:
                question  = sub.get("question", slug)
                token_id  = _extract_token_id(sub)
                yes_price = _extract_yes_price(sub)

                df_1min  = pd.DataFrame()
                df_1day = pd.DataFrame()
                entry    = {"slug": slug, "question": question, "modes": {}}

                if token_id:
                    for mode in ["1min", "1day"]:
                        try:
                            df = fetch_highfreq(token_id, mode=mode)
                            if not df.empty:
                                chart = plot_highfreq(df, question, mode=mode)
                                entry["modes"][mode] = {"df": df, "chart": chart}
                                if mode == "1min":
                                    df_1min = df
                                else:
                                    df_1day = df
                        except Exception as e:
                            print(f"[report] {question} {mode} 失败: {e}")

                all_entries.append(entry)

                changes = _compute_price_changes(
                    df_1min  if not df_1min.empty  else None,
                    df_1day if not df_1day.empty else None,
                )
                sub_options_out.append({
                    "question":    question,
                    "yes_price":   yes_price,
                    "changes":     changes,
                    "changes_str": _format_changes(changes),
                })

            m = sub_markets[0]
            top = sub_options_out[0] if sub_options_out else {}
            slug_data.append({
                "slug":        slug,
                "question":    m.get("question", slug),
                "yes_price":   _extract_yes_price(m),
                "is_multi":    is_multi,
                "sub_count":   len(sub_markets),
                "sub_options": sub_options_out if is_multi else [],
                "changes":     top.get("changes", {}),
                "changes_str": top.get("changes_str", ""),
            })

        except Exception as e:
            print(f"[report] _build_all_data: {slug} 失败: {e}")
            slug_data.append({
                "slug": slug, "question": slug, "yes_price": None,
                "is_multi": False, "sub_count": 0, "sub_options": [],
                "changes": {}, "changes_str": "",
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
            market = fetch_market(slug)
            if isinstance(market, list):
                m           = market[0]
                is_multi    = True
                sub_cnt     = len(market)
                sub_options = [
                    {"question": sub.get("question", ""), "yes_price": _extract_yes_price(sub)}
                    for sub in market
                ]
            else:
                m           = market
                is_multi    = False
                sub_cnt     = 1
                sub_options = []
            slug_data.append({
                "slug":        slug,
                "question":    m.get("question", slug),
                "yes_price":   _extract_yes_price(m),
                "is_multi":    is_multi,
                "sub_count":   sub_cnt,
                "sub_options": sub_options,
            })
        except Exception as e:
            print(f"[report] mpnews 快照: {slug} 失败: {e}")

    try:
        _apply_translations(slug_data)
    except Exception as e:
        print(f"[report] 翻译失败，使用原文: {e}")

    # ── 2. 收集详细高频数据 ──
    all_entries = _collect_all_highfreq_data(slugs)

    # ── 3. 构建 HTML 文章内容 ──
    def _price_str(d: dict) -> str:
        if d.get("is_multi"):
            return f"多选项（{d.get('sub_count', 0)} 个选项）"
        yp = d.get("yes_price")
        return f"{yp:.1%}" if yp is not None else "N/A"

    html_parts = [
        f"<h2>📊 Polymarket 市场报告</h2>",
        f"<p><b>更新时间：</b>{timestamp}</p>",
        "<h3>市场概览</h3>",
        "<table border='1' cellpadding='6' cellspacing='0'>",
        "<tr><th>市场</th><th>当前概率（YES）</th></tr>",
    ]
    for d in slug_data:
        if d.get("is_multi") and d.get("sub_options"):
            # 多选项市场：展开每个子选项
            def _opt_price(yp) -> str:
                return f"{yp:.1%}" if yp is not None else "N/A"
            sub_rows = "".join(
                f"<li>{opt['question']}：{_opt_price(opt.get('yes_price'))}</li>"
                for opt in d["sub_options"]
            )
            html_parts.append(
                f"<tr><td><ul>{sub_rows}</ul></td><td>—</td></tr>"
            )
        else:
            html_parts.append(
                f"<tr><td>{d['question']}</td><td>{_price_str(d)}</td></tr>"
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
