import json
import pandas as pd
from fetcher import fetch_market, fetch_price_history


def fetch_highfreq(token_id: str, mode: str = "1min") -> pd.DataFrame:
    """
    直接从 Polymarket API 拉取高频数据，不做任何本地缓存。
    token_id : clobTokenIds[0]，由 report.py 解析后传入
    mode     : "1min"（近1天）或 "1hour"（近30天）
    返回     : DataFrame，列：timestamp / price / datetime
    """
    df = fetch_price_history(token_id, mode=mode)

    if df.empty:
        print(f"[history] token_id={token_id} mode={mode} 未获取到数据")
    else:
        print(f"[history] token_id={token_id} mode={mode} 获取 {len(df)} 条")
    return df
