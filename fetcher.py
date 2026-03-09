import requests
import pandas as pd
import time

CLOB_API  = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


def fetch_market(slug: str) -> dict | list:
    """
    三级降级查询，兼容单市场和多选项市场：
      Level 1: /markets?slug=        → 普通单市场
      Level 2: /markets?group_slug=  → 多选项市场子列表
      Level 3: /events?slug=         → 通过事件查子市场列表
    返回：
      dict  → 单市场
      list  → 多选项市场的子市场列表（每个元素是 dict）
    """
    slug = slug.strip()
    print(f"[fetcher] fetch_market slug={repr(slug)}")

    # ── Level 1: 直接查 market slug ──
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[fetcher] L1 返回条数: {len(data) if isinstance(data, list) else 1}")
        if data:
            return data[0] if isinstance(data, list) else data
    except Exception as e:
        print(f"[fetcher] L1 失败: {e}")

    # ── Level 2: 查 group_slug ──
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"group_slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[fetcher] L2 返回条数: {len(data) if isinstance(data, list) else 0}")
        if data:
            return data if isinstance(data, list) else [data]
    except Exception as e:
        print(f"[fetcher] L2 失败: {e}")

    # ── Level 3: 查 events ──
    try:
        resp = requests.get(
            f"{GAMMA_API}/events",
            params={"slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
        print(f"[fetcher] L3 返回条数: {len(events) if isinstance(events, list) else 1}")
        if events:
            event = events[0] if isinstance(events, list) else events
            markets = event.get("markets", [])
            if markets:
                return markets   # list of dicts
    except Exception as e:
        print(f"[fetcher] L3 失败: {e}")

    raise ValueError(f"未找到 slug='{slug}' 对应的市场（三级查询均失败）")


def fetch_price_history(token_id: str, mode: str = "1min") -> pd.DataFrame:
    """
    拉取高频历史价格数据。
    mode:
      "1min" → fidelity=1,  interval=1d  （近1天，约1440条）
      "5min" → fidelity=5,  interval=1w  （近1周，约2016条）
    返回 DataFrame，列：timestamp(int), price(float), datetime(UTC)
    """
    mode_config = {
        "1min": {"fidelity": 1,  "intervals": ["1d"]},
        "5min": {"fidelity": 5,  "intervals": ["1d", "1w"]},
    }
    if mode not in mode_config:
        raise ValueError(f"mode 须为 '1min' 或 '5min'，当前传入: {mode}")

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

    # 截取目标时间窗口
    cutoff_days = 1 if mode == "1min" else 7
    cutoff = df["datetime"].max() - pd.Timedelta(days=cutoff_days)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)

    return df
