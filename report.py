import json
from datetime import datetime, timezone, timedelta
from history import fetch_highfreq
from fetcher import fetch_market
from analyzer import (
    analyze_snapshot,
    analyze_all_slugs,
    translate_to_chinese,
    translate_sub_options_short,
    summarize_highfreq,
    analyze_highfreq,
    plot_highfreq,
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

    overall = analyze_all_slugs(slug_data)
    send_summary_card(slug_data, overall, timestamp)
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
# mpnews：收集全量数据（不发消息）
# ──────────────────────────────────────────
def _collect_all_highfreq_data(slugs: list) -> list:
    """
    遍历所有 slug，拉取双粒度高频数据，返回结构化列表供 mpnews 使用。
    每个元素：{"slug": ..., "question": ..., "modes": {"1min": {...}, "5min": {...}}}
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
                for mode in ["1min", "5min"]:
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

    overall = analyze_all_slugs(slug_data)

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
        f"<p><b>整体解读：</b>{overall}</p>",
        "<hr/>",
        "<h3>详细走势分析</h3>",
    ]

    # ── 4. 上传图片并嵌入 HTML ──
    thumb_media_id: str | None = None
    for entry in all_entries:
        html_parts.append(f"<h4>{entry['question']}</h4>")
        for mode in ["1min", "5min"]:
            data = entry["modes"].get(mode)
            if not data:
                continue
            mode_label = "近1天（1分钟粒度）" if mode == "1min" else "近1周（5分钟粒度）"
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
        "digest":         overall[:120],
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

    # ── 降级：先发汇总卡片，再逐 slug 发送高频报告 ──
    try:
        run_slugs_summary(slugs)
    except Exception as e:
        send_text(f"⚠️ 汇总消息发送失败: {e}")
        print(f"[report] 汇总失败: {e}")

    for slug in slugs:
        for mode in ["1min", "5min"]:
            try:
                run_highfreq_report(slug, mode=mode)
            except Exception as e:
                send_text(f"❌ [{slug}] mode={mode} 报告失败: {e}")
                print(f"[report] 错误: {e}")


# ──────────────────────────────────────────
# 入口
# ──────────────────────────────────────────
if __name__ == "__main__":
    run_all_highfreq_reports(SLUGS)
