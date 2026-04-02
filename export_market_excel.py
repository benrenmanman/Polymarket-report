"""
导出指定 Polymarket 市场的所有数据到 Excel。
用法: python export_market_excel.py
"""

import os
import requests
import pandas as pd
import time
import json
from datetime import datetime, timezone

CLOB_API  = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

SLUG = os.environ.get("EXPORT_SLUG", "us-x-iran-ceasefire-by")


def fetch_market_all(slug: str):
    """
    多路径查询，严格验证每一步返回的 slug 字段。
    返回 list[dict]（可能包含多个子市场）。
    """
    slug = slug.strip()
    print(f"[export] 目标 slug={repr(slug)}")

    # ── 路径 1: /markets?slug=<slug> ──
    print("[export] 路径1: /markets?slug=")
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else ([data] if data else [])
        matched = [m for m in items if m.get("slug") == slug]
        print(f"  返回 {len(items)} 条，slug 精确匹配 {len(matched)} 条")
        if matched:
            return matched
    except Exception as e:
        print(f"  失败: {e}")

    # ── 路径 2: /events?slug=<slug>，从 event.markets 取子市场 ──
    print("[export] 路径2: /events?slug=")
    try:
        resp = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        items = events if isinstance(events, list) else ([events] if events else [])
        print(f"  返回 {len(items)} 个 event")
        for ev in items:
            ev_slug = ev.get("slug", "")
            markets = ev.get("markets", [])
            print(f"  event slug={repr(ev_slug)}, 子市场={len(markets)}")
            if ev_slug == slug and markets:
                print(f"  ✓ 精确匹配，返回 {len(markets)} 个子市场")
                return markets
        print("  无精确匹配的 event")
    except Exception as e:
        print(f"  失败: {e}")

    # ── 路径 3: /events?title=<slug>（关键词搜索） ──
    print("[export] 路径3: /events?title=（关键词）")
    keyword = slug.replace("-", " ")
    try:
        resp = requests.get(f"{GAMMA_API}/events", params={"title": keyword}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        items = events if isinstance(events, list) else ([events] if events else [])
        print(f"  关键词={repr(keyword)}，返回 {len(items)} 个 event")
        for ev in items:
            ev_slug = ev.get("slug", "")
            markets = ev.get("markets", [])
            print(f"  event slug={repr(ev_slug)}, 子市场={len(markets)}")
        # 优先精确匹配，否则取第一个有子市场的 event
        for ev in items:
            if ev.get("slug") == slug and ev.get("markets"):
                return ev["markets"]
        for ev in items:
            if ev.get("markets"):
                print(f"  使用第一个有子市场的 event: slug={repr(ev.get('slug'))}")
                return ev["markets"]
    except Exception as e:
        print(f"  失败: {e}")

    # ── 路径 4: /markets?slug= 宽松匹配（slug 包含目标词） ──
    print("[export] 路径4: /markets 宽松关键词搜索")
    keyword_part = slug.split("-")[0]  # 取首段词，如 "us"
    # 用更有意义的部分
    parts = slug.split("-")
    keyword_part = "-".join(parts[:4]) if len(parts) >= 4 else slug
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params={"slug": keyword_part}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else ([data] if data else [])
        matched = [m for m in items if m.get("slug", "").startswith(keyword_part) or slug in m.get("slug", "")]
        print(f"  关键词={repr(keyword_part)}，返回 {len(items)} 条，相关 {len(matched)} 条")
        if matched:
            for m in matched:
                print(f"  候选: slug={repr(m.get('slug'))}")
            return matched
    except Exception as e:
        print(f"  失败: {e}")

    raise ValueError(
        f"所有路径均未找到 slug='{slug}' 对应的市场。\n"
        f"请确认该市场已在 Polymarket 上线，或在 https://polymarket.com 上查找正确的 slug。"
    )


def fetch_price_history_full(token_id: str, label: str = "") -> pd.DataFrame:
    """拉取全量日线 + 近1天1分钟数据"""
    print(f"[export] 拉取价格历史 token={token_id[:16]}... {label}")
    frames = []

    for fidelity, interval, desc in [(1440, "max", "日线(全量)"), (1, "1d", "1分钟(近1天)")]:
        try:
            resp = requests.get(
                f"{CLOB_API}/prices-history",
                params={"market": token_id, "interval": interval, "fidelity": fidelity},
                timeout=15,
            )
            resp.raise_for_status()
            history = resp.json().get("history", [])
            if history:
                df = pd.DataFrame(history).rename(columns={"t": "timestamp", "p": "price"})
                df["granularity"] = desc
                frames.append(df)
                print(f"    {desc}: {len(df)} 条")
        except Exception as e:
            print(f"    {desc} 失败: {e}")
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "price", "datetime", "granularity"])

    df = pd.concat(frames, ignore_index=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_localize(None)
    df["price"] = df["price"].astype(float)
    df = df.sort_values(["granularity", "datetime"]).reset_index(drop=True)
    return df


def flatten_market(m: dict) -> dict:
    """将市场 dict 展开为平铺结构"""
    skip_keys = {"outcomes", "outcomePrices", "clobTokenIds",
                 "rewardsMinSize", "rewardsMaxSpread", "fpmm",
                 "groupItemTagged", "groupItemTitle"}
    row = {}
    for k, v in m.items():
        if k in skip_keys:
            continue
        row[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v

    for field, prefix in [("outcomes", "outcome"), ("outcomePrices", "price"), ("clobTokenIds", "token")]:
        val = m.get(field)
        if isinstance(val, list):
            for i, x in enumerate(val):
                row[f"{prefix}_{i}"] = x

    return row


def extract_deadline_label(question: str, slug: str) -> str:
    """从问题文本或 slug 中提取截止日期标签，如 'Apr 7' 'Mar 31'"""
    import re
    # 优先从 question 中提取，如 "by April 7?" → "Apr 7"
    m = re.search(r'by\s+([A-Za-z]+\s+\d+)', question, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        try:
            dt = datetime.strptime(raw, "%B %d")
            return dt.strftime("%b %-d")
        except Exception:
            return raw
    # 从 slug 中提取末尾日期部分，如 "...-april-7-278" → "Apr 7"
    m = re.search(r'-([a-z]+-\d+)(?:-\d+)?$', slug)
    if m:
        parts = m.group(1).split("-")
        if len(parts) == 2:
            try:
                dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%B %d")
                return dt.strftime("%b %-d")
            except Exception:
                pass
    return question[:20]


def fetch_daily_yes(token_id: str) -> pd.Series:
    """只拉全量日线，返回以日期为 index、YES 价格为值的 Series"""
    try:
        resp = requests.get(
            f"{CLOB_API}/prices-history",
            params={"market": token_id, "interval": "max", "fidelity": 1440},
            timeout=15,
        )
        resp.raise_for_status()
        history = resp.json().get("history", [])
        if not history:
            return pd.Series(dtype=float)
        df = pd.DataFrame(history).rename(columns={"t": "timestamp", "p": "price"})
        df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.normalize().dt.tz_localize(None)
        df["price"] = df["price"].astype(float)
        # 每天取最后一条（最新价）
        df = df.sort_values("date").drop_duplicates(subset="date", keep="last")
        return df.set_index("date")["price"]
    except Exception as e:
        print(f"    日线拉取失败: {e}")
        return pd.Series(dtype=float)
    finally:
        time.sleep(0.3)


def main():
    markets = fetch_market_all(SLUG)
    print(f"\n共找到 {len(markets)} 个市场")
    for m in markets:
        print(f"  slug={repr(m.get('slug'))}  question={m.get('question','')[:60]}")

    df_meta = pd.DataFrame([flatten_market(m) for m in markets])

    # ── 收集各市场数据 ──
    price_sheets = {}        # 原始价格历史 sheets
    daily_series = {}        # 用于汇总的日度 YES 概率

    for m in markets:
        question = m.get("question", m.get("slug", "unknown"))
        slug_m   = m.get("slug", "")
        label    = extract_deadline_label(question, slug_m)

        tokens = m.get("clobTokenIds") or []
        if isinstance(tokens, str):
            try: tokens = json.loads(tokens)
            except: tokens = []
        outcomes = m.get("outcomes") or []
        if isinstance(outcomes, str):
            try: outcomes = json.loads(outcomes)
            except: outcomes = []

        for i, token_id in enumerate(tokens):
            outcome_label = outcomes[i] if i < len(outcomes) else f"token{i}"
            df_h = fetch_price_history_full(token_id, f"{question[:20]}_{outcome_label}")
            if not df_h.empty:
                df_h["market_question"] = question[:60]
                df_h["outcome"] = outcome_label
                df_h["token_id"] = token_id
                key = f"{label}_{outcome_label}"
                price_sheets[key] = df_h

            # 只取 YES（index 0）构建汇总日度序列
            if i == 0:
                print(f"[export] 日度汇总: {label} (YES token)")
                s = fetch_daily_yes(token_id)
                if not s.empty:
                    daily_series[label] = s

    # ── 构建日度概率汇总宽表 ──
    # 按截止日期时间顺序排列各列
    def sort_key(label):
        try:
            return datetime.strptime(label + " 2025", "%b %d %Y")
        except Exception:
            return datetime.max

    sorted_labels = sorted(daily_series.keys(), key=sort_key)
    df_daily = pd.DataFrame({lbl: daily_series[lbl] for lbl in sorted_labels})
    df_daily.index.name = "date"
    df_daily = df_daily.sort_index()
    # 向前填充（节假日/无交易日用前一天价格）
    df_daily = df_daily.ffill()
    df_daily = df_daily.round(4)

    # ── 写 Excel ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"polymarket_{SLUG}_{ts}.xlsx"
    print(f"\n[export] 写入 {filename} ...")

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        # Sheet 1: 日度概率汇总（最重要，放最前）
        df_daily_out = df_daily.reset_index()
        df_daily_out.to_excel(writer, sheet_name="日度概率汇总(YES)", index=False)
        print(f"  ✓ 日度概率汇总(YES)  {len(df_daily)} 行 × {len(df_daily.columns)} 列")

        # Sheet 2: 市场元数据
        df_meta.to_excel(writer, sheet_name="市场元数据", index=False)
        print(f"  ✓ 市场元数据 ({len(df_meta)} 行)")

        # Sheet 3+: 各市场原始价格历史
        for sheet_name, df_h in price_sheets.items():
            safe = sheet_name[:31]
            df_h.to_excel(writer, sheet_name=safe, index=False)
            print(f"  ✓ {safe} ({len(df_h)} 行)")

    print(f"\n完成！文件: {filename}")
    return filename


if __name__ == "__main__":
    main()
