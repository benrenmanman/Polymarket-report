from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timezone

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
    """读取最近 N 条快照，按时间升序"""
    resp = (
        get_client()
        .table("snapshots")
        .select("id, data, created_at")
        .eq("slug", slug)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(resp.data or []))


def get_latest_snapshot(slug: str) -> dict | None:
    """读取最新一条快照"""
    resp = (
        get_client()
        .table("snapshots")
        .select("id, data, created_at")
        .eq("slug", slug)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def get_snapshot_at(slug: str, target_time: datetime) -> dict | None:
    """
    取距离 target_time 最近的一条快照（只往前找，不超过目标时间）
    """
    resp = (
        get_client()
        .table("snapshots")
        .select("id, data, created_at")
        .eq("slug", slug)
        .lte("created_at", target_time.isoformat())   # 不超过目标时间
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None
