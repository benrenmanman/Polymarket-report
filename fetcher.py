import requests
import pandas as pd
import time
from datetime import datetime, timezone

CLOB_API  = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


def _is_active_market(m: dict) -> bool:
    if not m.get("active", True):
        return False
    if m.get("closed", False):
        return False
    if m.get("archived", False):
        return False
    end_date = m.get("endDateIso") or m.get("end_date_iso")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt < datetime.now(timezone.utc):
                return False
        except Exception:
            pass
    return True


def fetch_market(slug: str) -> dict | list:
    """
    二级降级查询，兼容单市场和多选项市场。
    返回：dict（单市场）或 list（多选项子市场列表）
    """
    slug = slug.strip()
    print(f"[fetcher] fetch_market slug={repr(slug)}")

    # Level 1: /markets?slug= 精确匹配 slug 字段
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else ([data] if data else [])
        matched = [m for m in items if m.get("slug") == slug]
        print(f"[fetcher] L1 返回条数: {len(items)}，精确匹配: {len(matched)}")
        if matched:
            return matched[0]
    except Exception as e:
        print(f"[fetcher] L1 失败: {e}")

    # Level 2: /events?slug= 精确匹配 event slug，提取子市场（多选项市场）
    # 注意：不使用 group_slug 路径——当 slug 不匹配时该接口会返回默认的20个无关市场
    try:
        resp = requests.get(
            f"{GAMMA_API}/events",
            params={"slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
        items = events if isinstance(events, list) else ([events] if events else [])
        print(f"[fetcher] L2 event 条数: {len(items)}")
        for ev in items:
            if ev.get("slug") == slug:
                markets = [m for m in ev.get("markets", []) if _is_active_market(m)]
                print(f"[fetcher] L2 精确匹配，活跃子市场: {len(markets)}")
                if markets:
                    return markets
    except Exception as e:
        print(f"[fetcher] L2 失败: {e}")

    raise ValueError(f"未找到 slug='{slug}' 对应的市场（二级查询均失败）")


def fetch_markets_batch(slugs: list) -> dict:
    """
    批量拉取多个 slug 的市场数据。
    返回 {slug: market_data}，market_data 为 dict 或 list。
    单个 slug 失败时记录错误并继续，不中断整体流程。
    """
    results = {}
    for slug in slugs:
        try:
            results[slug] = fetch_market(slug)
        except Exception as e:
            print(f"[fetcher] batch: slug={slug} 获取失败: {e}")
            results[slug] = None
        time.sleep(0.3)   # 避免请求过于密集
    return results


def fetch_price_history(token_id: str, mode: str = "1min") -> pd.DataFrame:
    """
    拉取历史价格数据。
    mode:
      "1min"  → fidelity=1,    interval=1d（近1天，约1440条）
      "1day"  → fidelity=1440, interval=1m（近30天，约30条）
    返回 DataFrame，列：timestamp(int), price(float), datetime(UTC)
    """
    mode_config = {
        "1min":  {"fidelity": 1,    "intervals": ["1d"]},
        "1day":  {"fidelity": 1440, "intervals": ["max"]},   # 全量日线，截取近30天
    }
    if mode not in mode_config:
        raise ValueError(f"mode 须为 '1min' 或 '1day'，当前传入: {mode}")

    cfg       = mode_config[mode]
    fidelity  = cfg["fidelity"]
    intervals = cfg["intervals"]

    all_frames = []
    for itv in intervals:
        try:
            resp = requests.get(
                f"{CLOB_API}/prices-history",
                params={"market": token_id, "interval": itv, "fidelity": fidelity},
                timeout=10,
            )
            resp.raise_for_status()
            history = resp.json().get("history", [])
            if history:
                df_part = pd.DataFrame(history).rename(
                    columns={"t": "timestamp", "p": "price"}
                )
                all_frames.append(df_part)
        except Exception as e:
            print(f"[fetcher] interval={itv} fidelity={fidelity} 请求失败: {e}")
        time.sleep(0.3)

    if not all_frames:
        return pd.DataFrame(columns=["timestamp", "price", "datetime"])

    df = pd.concat(all_frames, ignore_index=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["price"]    = df["price"].astype(float)
    df = (
        df.drop_duplicates(subset="timestamp")
          .sort_values("datetime")
          .reset_index(drop=True)
    )

    cutoff_days = 1 if mode == "1min" else 30
    cutoff = df["datetime"].max() - pd.Timedelta(days=cutoff_days)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)

    return df
