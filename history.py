import json
import pandas as pd
from fetcher import fetch_market, fetch_price_history


def fetch_highfreq(slug: str, mode: str = "1min") -> pd.DataFrame:
    """
    直接从 Polymarket API 拉取高频数据，不做任何本地缓存。
    slug : 市场 slug
    mode : "1min"（近1天）或 "5min"（近1周）
    返回  : DataFrame，列：timestamp / price / datetime
    """
    market    = fetch_market(slug)
    token_ids = market.get("clobTokenIds", "[]")
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    if not token_ids:
        print(f"[history] {slug} 无 clobTokenIds，返回空 DataFrame")
        return pd.DataFrame(columns=["timestamp", "price", "datetime"])

    token_id = token_ids[0]
    df = fetch_price_history(token_id, mode=mode)

    if df.empty:
        print(f"[history] {slug} mode={mode} 未获取到数据")
    else:
        print(f"[history] {slug} mode={mode} 获取 {len(df)} 条")
    return df
