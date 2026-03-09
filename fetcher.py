import requests
import pandas as pd
import time

CLOB_API  = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


def fetch_market(slug: str) -> dict:
    """原有函数，保持不变"""
    url = f"{GAMMA_API}/markets"
    resp = requests.get(url, params={"slug": slug}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError(f"未找到 slug='{slug}' 对应的市场")
    return data[0] if isinstance(data, list) else data


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
