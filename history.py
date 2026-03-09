import json
import os
import pandas as pd
from config import HISTORY_DIR          # 原有配置，保持不动
from fetcher import fetch_market, fetch_price_history
from db import save_snapshot            # 原有函数，保持不动


# ──────────────────────────────────────────
# 原有函数（保持不变）
# ──────────────────────────────────────────
def load_history(slug: str) -> list:
    path = os.path.join(HISTORY_DIR, f"{slug}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def save_history(slug: str, data: list):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = os.path.join(HISTORY_DIR, f"{slug}.json")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────
# 新增：高频历史数据本地缓存
# ──────────────────────────────────────────
def _highfreq_path(slug: str, mode: str) -> str:
    """高频数据存储路径，与原有 history 目录隔离"""
    dir_path = os.path.join(HISTORY_DIR, "highfreq", mode)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{slug}.parquet")


def fetch_and_save_highfreq(slug: str, mode: str = "1min") -> pd.DataFrame:
    """
    拉取高频数据并保存到本地 parquet 缓存（增量合并）。

    slug : 市场 slug
    mode : "1min"（近1天）或 "5min"（近1周）
    返回  : 合并后的完整 DataFrame
    """
    import json as _json

    # 1. 获取 token_id
    market    = fetch_market(slug)
    token_ids = market.get("clobTokenIds", "[]")
    if isinstance(token_ids, str):
        token_ids = _json.loads(token_ids)
    if not token_ids:
        raise ValueError(f"[history] {slug} 无 clobTokenIds")
    token_id = token_ids[0]

    # 2. 拉取最新高频数据
    df_new = fetch_price_history(token_id, mode=mode)
    if df_new.empty:
        print(f"[history] {slug} mode={mode} 未获取到数据")
        return df_new

    # 3. 增量合并本地缓存
    path = _highfreq_path(slug, mode)
    if os.path.exists(path):
        df_old = pd.read_parquet(path)
        df = (
            pd.concat([df_old, df_new], ignore_index=True)
              .drop_duplicates(subset="timestamp")
              .sort_values("datetime")
              .reset_index(drop=True)
        )
    else:
        df = df_new

    # 4. 只保留目标窗口（避免文件无限增大）
    cutoff_days = 1 if mode == "1min" else 7
    cutoff = df["datetime"].max() - pd.Timedelta(days=cutoff_days)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)

    # 5. 保存
    df.to_parquet(path, index=False)
    print(f"[history] {slug} mode={mode} 已保存 {len(df)} 条 → {path}")
    return df


def load_highfreq(slug: str, mode: str = "1min") -> pd.DataFrame:
    """从本地缓存读取高频数据"""
    path = _highfreq_path(slug, mode)
    if not os.path.exists(path):
        return pd.DataFrame(columns=["timestamp", "price", "datetime"])
    return pd.read_parquet(path)
