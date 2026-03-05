from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

_client = None

def get_client():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def save_snapshot(slug: str, data: dict):
    """存入一条快照"""
    get_client().table("snapshots").insert({
        "slug": slug,
        "data": data
    }).execute()


def get_recent_snapshots(slug: str, limit: int = 6) -> list[dict]:
    """
    读取最近 N 条快照（默认6条 = 过去1小时，每10分钟一条）
    返回按时间升序排列的 data 列表
    """
    resp = (
        get_client()
        .table("snapshots")
        .select("data, created_at")
        .eq("slug", slug)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = resp.data or []
    # 反转为时间升序，方便趋势分析
    return list(reversed(rows))
