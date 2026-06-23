"""
霍尔木兹海峡通行快照的本地累积与趋势计算（方案 B）。

aisstream 只有实时流、无历史接口，故由定期报告**每次把当次采样快照
追加写入本地 JSON**，逐步攒成时间序列；报告再据此展示"过去 24h 趋势"。
该 JSON 由 GitHub Actions 工作流在每次运行后提交回仓库实现跨运行持久化。
"""
import json
import os
from datetime import datetime, timezone, timedelta

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def load_history(path: str) -> list:
    """读取历史快照列表；文件不存在/损坏时返回空列表。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        snaps = data.get("snapshots", []) if isinstance(data, dict) else data
        return snaps if isinstance(snaps, list) else []
    except Exception as e:
        print(f"[hormuz_history] 读取失败: {e}")
        return []


def _record(stats: dict, ts: datetime) -> dict:
    """从一次聚合统计中抽取需要长期保存的精简字段。"""
    return {
        "ts":        ts.strftime(_TS_FMT),
        "area":      stats.get("area", "strait"),
        "frames":    stats.get("msg_count", 0),
        "total":     stats.get("total", 0),
        "moving":    stats.get("moving", 0),
        "anchored":  stats.get("anchored", 0),
        "eastbound": stats.get("eastbound", 0),
        "westbound": stats.get("westbound", 0),
        "avg_speed": stats.get("avg_speed"),
        "tankers":   (stats.get("type_counts") or {}).get("油轮", 0),
    }


def append_snapshot(stats: dict, path: str, retention_hours: int = 24) -> list:
    """
    追加当次快照、剪掉超出保留窗口的旧记录，写回文件，返回更新后的列表。
    保留窗口默认 24h（多留 1h 余量以便"约 24h 前"的对比更稳）。
    """
    history = load_history(path)
    now = datetime.now(timezone.utc)
    history.append(_record(stats, now))

    cutoff = now - timedelta(hours=retention_hours + 1)
    pruned = []
    for r in history:
        try:
            t = datetime.strptime(r.get("ts", ""), _TS_FMT).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if t >= cutoff:
            pruned.append(r)
    pruned.sort(key=lambda r: r["ts"])
    pruned = pruned[-1000:]   # 安全上限，防异常无限增长

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"snapshots": pruned}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[hormuz_history] 写入失败: {e}")
    return pruned


def _span_hours(earliest: dict, latest: dict) -> float:
    try:
        t0 = datetime.strptime(earliest["ts"], _TS_FMT)
        t1 = datetime.strptime(latest["ts"], _TS_FMT)
        return max(0.0, (t1 - t0).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def summarize_trend(history: list) -> dict:
    """
    计算趋势摘要（供卡片展示）。history 须按时间升序。
    返回 points / span_hours / 当前值 / 较上次 / 较最早 / 区间极值。
    """
    if not history:
        return {"points": 0}

    latest   = history[-1]
    prev     = history[-2] if len(history) >= 2 else None
    earliest = history[0]
    totals   = [r.get("total", 0) for r in history]

    return {
        "points":           len(history),
        "span_hours":       _span_hours(earliest, latest),
        "total_now":        latest.get("total", 0),
        "total_prev":       prev.get("total") if prev else None,
        "total_earliest":   earliest.get("total") if prev else None,  # 仅多于1点时有意义
        "total_max":        max(totals),
        "total_min":        min(totals),
        "tankers_now":      latest.get("tankers", 0),
        "frames_now":       latest.get("frames", 0),
    }
