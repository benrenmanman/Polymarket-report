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
    """不过滤 active/closed，返回所有匹配的市场数据（包括已关闭的）"""
    slug = slug.strip()
    print(f"[export] 查询 slug={repr(slug)}")

    # Level 1: 直接查 market slug，严格验证返回结果的 slug 字段
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data:
            result = data if isinstance(data, list) else [data]
            # 只保留 slug 字段完全匹配的记录，避免 API 返回默认列表
            matched = [m for m in result if m.get("slug") == slug]
            if matched:
                print(f"[export] L1 精确匹配 {len(matched)} 条")
                return matched
            else:
                print(f"[export] L1 返回 {len(result)} 条但 slug 均不匹配，跳过")
    except Exception as e:
        print(f"[export] L1 失败: {e}")

    # Level 2: 查 group_slug，验证 groupSlug 字段
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params={"group_slug": slug}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data:
            result = data if isinstance(data, list) else [data]
            matched = [m for m in result if m.get("groupSlug") == slug or m.get("group_slug") == slug]
            if matched:
                print(f"[export] L2 精确匹配 {len(matched)} 条")
                return matched
            elif result:
                # group_slug 查询结果本身就是该 group 的子市场，直接使用
                print(f"[export] L2 返回 {len(result)} 条（子市场）")
                return result
    except Exception as e:
        print(f"[export] L2 失败: {e}")

    # Level 3: 查 events
    try:
        resp = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        if events:
            event = events[0] if isinstance(events, list) else events
            markets = event.get("markets", [])
            print(f"[export] L3 event 找到 {len(markets)} 个子市场")
            return markets
    except Exception as e:
        print(f"[export] L3 失败: {e}")

    raise ValueError(f"未找到 slug='{slug}' 对应的市场")


def fetch_price_history_full(token_id: str, label: str = "") -> pd.DataFrame:
    """拉取全量日线数据（max interval）"""
    print(f"[export] 拉取价格历史 token_id={token_id[:12]}... {label}")
    frames = []

    # 全量日线
    for fidelity, interval, desc in [(1440, "max", "全量日线"), (1, "1d", "1分钟/近1天")]:
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
                df["fidelity"] = desc
                frames.append(df)
                print(f"  {desc}: {len(df)} 条")
        except Exception as e:
            print(f"  {desc} 失败: {e}")
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "price", "datetime", "fidelity"])

    df = pd.concat(frames, ignore_index=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["price"] = df["price"].astype(float)
    df = df.sort_values(["fidelity", "datetime"]).reset_index(drop=True)
    return df


def flatten_market(m: dict) -> dict:
    """将市场 dict 展开为适合 DataFrame 的平铺结构"""
    row = {}
    skip_keys = {"outcomes", "outcomePrices", "clobTokenIds", "rewardsMinSize",
                 "rewardsMaxSpread", "fpmm", "groupItemTagged", "groupItemTitle"}
    for k, v in m.items():
        if k in skip_keys:
            continue
        if isinstance(v, (dict, list)):
            row[k] = json.dumps(v, ensure_ascii=False)
        else:
            row[k] = v

    # 单独处理关键字段
    outcomes = m.get("outcomes")
    prices   = m.get("outcomePrices")
    tokens   = m.get("clobTokenIds")

    if isinstance(outcomes, list):
        for i, o in enumerate(outcomes):
            row[f"outcome_{i}"] = o
    if isinstance(prices, list):
        for i, p in enumerate(prices):
            row[f"price_{i}"] = p
    if isinstance(tokens, list):
        for i, t in enumerate(tokens):
            row[f"token_{i}"] = t

    return row


def main():
    markets = fetch_market_all(SLUG)
    print(f"\n共找到 {len(markets)} 个市场\n")

    # ── Sheet 1: 市场元数据 ──
    meta_rows = [flatten_market(m) for m in markets]
    df_meta = pd.DataFrame(meta_rows)

    # ── Sheet 2+: 每个子市场的价格历史 ──
    price_sheets = {}
    for m in markets:
        question = m.get("question", m.get("slug", "unknown"))[:40]
        tokens = m.get("clobTokenIds") or []
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                tokens = []

        outcomes = m.get("outcomes") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = []

        for i, token_id in enumerate(tokens):
            outcome_label = outcomes[i] if i < len(outcomes) else f"token{i}"
            label = f"{question[:20]}_{outcome_label}"
            df_h = fetch_price_history_full(token_id, label)
            if not df_h.empty:
                df_h["market_question"] = question
                df_h["outcome"] = outcome_label
                df_h["token_id"] = token_id
                price_sheets[f"price_{i}_{outcome_label[:15]}"] = df_h

    # ── 写 Excel ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"polymarket_{SLUG}_{ts}.xlsx"
    print(f"\n[export] 写入 {filename} ...")

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df_meta.to_excel(writer, sheet_name="市场元数据", index=False)
        print(f"  ✓ 市场元数据 ({len(df_meta)} 行)")

        for sheet_name, df_h in price_sheets.items():
            safe_name = sheet_name[:31]  # Excel sheet name max 31 chars
            df_h.to_excel(writer, sheet_name=safe_name, index=False)
            print(f"  ✓ {safe_name} ({len(df_h)} 行)")

    print(f"\n完成！文件已保存为: {filename}")
    return filename


if __name__ == "__main__":
    main()
