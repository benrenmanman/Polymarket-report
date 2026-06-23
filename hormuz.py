"""
霍尔木兹海峡（Strait of Hormuz）实时通行情况跟踪。

数据来源：AISStream.io（https://aisstream.io/）实时 AIS WebSocket 流。
本模块连接 aisstream，订阅霍尔木兹海峡边界框，在固定窗口内收集
船舶位置报文（PositionReport）与船舶静态信息（ShipStaticData），
聚合为通行态势统计，供定期报告使用。

设计要点：
  · aisstream 为 WebSocket 推流，而本项目报告为一次性脚本，
    因此采用"连接 → 订阅 → 采样固定时长 → 断开 → 聚合"的方式。
  · 全程防御式解析（.get + 哨兵值过滤），单点异常不影响整体报告。
  · 不在源码中硬编码 API Key，统一从环境变量读取（见 config.py）。
"""
import asyncio
import json
import time
from collections import defaultdict

import websockets

from config import (
    AISSTREAM_API_KEY,
    HORMUZ_BBOX,
    HORMUZ_WINDOW_SEC,
)

AIS_WS_URL = "wss://stream.aisstream.io/v0/stream"

# AIS 哨兵值（表示"不可用"），需在统计前剔除
_SOG_NA     = 102.0   # 航速 ≥ 102.3 节即"不可用"
_COG_NA     = 360.0   # 航向 = 360° 即"不可用"
_HEADING_NA = 511     # 真航向 = 511 即"不可用"
_MOVING_MIN = 0.5     # 航速 ≥ 0.5 节视为"航行中"


# ──────────────────────────────────────────
# AIS 船舶类型代码 → 中文分类
# 依据 ITU-R M.1371 船舶与货物类型编码
# ──────────────────────────────────────────
def ship_type_category(type_code) -> str:
    """将 AIS ShipStaticData.Type 代码映射为中文船型分类。无效时归为'未知'。"""
    try:
        t = int(type_code)
    except (TypeError, ValueError):
        return "未知"
    if t <= 0:
        return "未知"
    if 80 <= t <= 89:
        return "油轮"            # Tanker（含油气运输船）
    if 70 <= t <= 79:
        return "货船"            # Cargo
    if 60 <= t <= 69:
        return "客船"            # Passenger
    if 40 <= t <= 49:
        return "高速船"          # High-speed craft
    if t == 30:
        return "渔船"            # Fishing
    if t in (31, 32, 52):
        return "拖轮/作业船"     # Towing / Tug
    if t in (33, 34, 53, 54):
        return "工程/作业船"     # Dredging / Diving / Port tender / Anti-pollution
    if t in (35, 55):
        return "军警船"          # Military / Law enforcement
    if t in (36, 37):
        return "帆船/游艇"       # Sailing / Pleasure craft
    if t in (50, 51):
        return "引航/搜救船"     # Pilot / SAR
    return "其他"


def _clean(s) -> str:
    """清洗 AIS 文本字段（船名/目的地常带尾随 @ 或空白填充）。"""
    if not s:
        return ""
    return str(s).replace("@", "").strip()


def _classify_direction(cog) -> str | None:
    """
    依据航向判定通行方向。霍尔木兹海峡西接波斯湾、东连阿曼湾，
    主航道呈西北—东南走向：
      · 东行（出湾）：驶向阿曼湾/印度洋，航向含东向分量 [0, 180)
      · 西行（入湾）：驶入波斯湾，航向含西向分量 [180, 360)
    航向不可用时返回 None。
    """
    if not isinstance(cog, (int, float)):
        return None
    if cog < 0 or cog >= _COG_NA:
        return None
    return "east" if cog < 180 else "west"


# ──────────────────────────────────────────
# WebSocket 采样（异步）
# ──────────────────────────────────────────
async def _stream(api_key: str, bbox: list, window_sec: int):
    """
    连接 aisstream，订阅 bbox，采样 window_sec 秒。
    返回 (positions, statics, msg_count, error)：
      · positions: {mmsi: 最新位置报文 dict}
      · statics  : {mmsi: 船舶静态信息 dict}
      · msg_count: 收到的有效报文总数
      · error    : 服务端返回的错误字符串（鉴权/订阅格式错误等），无则 None
    """
    subscribe = {
        "APIKey": api_key,
        "BoundingBoxes": [bbox],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }

    positions: dict = {}
    statics: dict = {}
    msg_count = 0
    error = None
    deadline = time.monotonic() + window_sec

    async with websockets.connect(
        AIS_WS_URL,
        open_timeout=20,
        ping_interval=20,
        ping_timeout=20,
        max_size=2 ** 21,
    ) as ws:
        await ws.send(json.dumps(subscribe))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue

            # 服务端错误（订阅格式错误、API Key 无效等）以 {"error": "..."} 返回
            if isinstance(msg, dict) and msg.get("error"):
                error = str(msg.get("error"))
                break

            mtype = msg.get("MessageType")
            meta  = msg.get("MetaData") or {}
            body  = msg.get("Message") or {}
            mmsi  = meta.get("MMSI")

            if mtype == "PositionReport":
                pr = body.get("PositionReport") or {}
                if mmsi is None:
                    mmsi = pr.get("UserID")
                if mmsi is None:
                    continue
                msg_count += 1
                positions[mmsi] = {
                    "mmsi":    mmsi,
                    "name":    _clean(meta.get("ShipName")),
                    "lat":     pr.get("Latitude"),
                    "lon":     pr.get("Longitude"),
                    "sog":     pr.get("Sog"),
                    "cog":     pr.get("Cog"),
                    "heading": pr.get("TrueHeading"),
                    "nav":     pr.get("NavigationalStatus"),
                    "time":    meta.get("time_utc"),
                }
            elif mtype == "ShipStaticData":
                sd = body.get("ShipStaticData") or {}
                if mmsi is None:
                    mmsi = sd.get("UserID")
                if mmsi is None:
                    continue
                msg_count += 1
                statics[mmsi] = {
                    "type":        sd.get("Type"),
                    "name":        _clean(sd.get("Name")) or _clean(meta.get("ShipName")),
                    "destination": _clean(sd.get("Destination")),
                    "draught":     sd.get("MaximumStaticDraught"),
                    "imo":         sd.get("ImoNumber"),
                }

    return positions, statics, msg_count, error


# ──────────────────────────────────────────
# 聚合统计
# ──────────────────────────────────────────
def _aggregate(positions: dict, statics: dict, msg_count: int,
               window_sec: int, bbox: list) -> dict:
    """将原始报文聚合为通行态势统计 dict。"""
    total = len(positions)
    moving = anchored = eastbound = westbound = 0
    speeds: list[float] = []
    type_counts: dict[str, int] = defaultdict(int)
    tankers: list[dict] = []

    for mmsi, p in positions.items():
        st  = statics.get(mmsi, {})
        cat = ship_type_category(st.get("type"))
        type_counts[cat] += 1

        sog = p.get("sog")
        cog = p.get("cog")
        nav = p.get("nav")

        is_moving = isinstance(sog, (int, float)) and _MOVING_MIN <= sog < _SOG_NA
        if is_moving:
            moving += 1
            speeds.append(float(sog))
            direction = _classify_direction(cog)
            if direction == "east":
                eastbound += 1
            elif direction == "west":
                westbound += 1
        elif nav in (1, 5) or (isinstance(sog, (int, float)) and sog < _MOVING_MIN):
            # 1=锚泊 5=系泊，或航速近 0
            anchored += 1

        if cat == "油轮":
            tankers.append({
                "name":        st.get("name") or p.get("name") or f"MMSI {mmsi}",
                "sog":         float(sog) if is_moving else None,
                "direction":   _classify_direction(cog) if is_moving else None,
                "destination": st.get("destination", ""),
            })

    avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else None

    # 重点油轮：航行中的优先、按航速降序，最多取 6 条
    tankers.sort(key=lambda t: (t["sog"] is None, -(t["sog"] or 0.0)))
    tankers = tankers[:6]

    return {
        "ok":           True,
        "error":        None,
        "window_sec":   window_sec,
        "bbox":         bbox,
        "msg_count":    msg_count,
        "total":        total,
        "moving":       moving,
        "anchored":     anchored,
        "eastbound":    eastbound,
        "westbound":    westbound,
        "avg_speed":    avg_speed,
        "type_counts":  dict(type_counts),
        "tankers":      tankers,
    }


# ──────────────────────────────────────────
# 对外同步接口
# ──────────────────────────────────────────
def collect_hormuz_traffic(window_sec: int | None = None,
                           bbox: list | None = None) -> dict:
    """
    采样霍尔木兹海峡通行情况并返回聚合统计（同步封装，内部跑 asyncio）。

    返回 dict：
      成功 → {"ok": True, "total":..., "moving":..., "eastbound":...,
              "westbound":..., "avg_speed":..., "type_counts":{...},
              "tankers":[...], "msg_count":..., "window_sec":..., "bbox":...}
      失败 → {"ok": False, "error": "原因", ...}
    """
    if not AISSTREAM_API_KEY:
        return {"ok": False, "error": "未配置 AISSTREAM_API_KEY", "total": 0}

    window_sec = window_sec or HORMUZ_WINDOW_SEC
    bbox = bbox or HORMUZ_BBOX

    try:
        positions, statics, msg_count, error = asyncio.run(
            _stream(AISSTREAM_API_KEY, bbox, window_sec)
        )
    except Exception as e:
        return {"ok": False, "error": f"AIS 连接/采样失败: {e}", "total": 0,
                "window_sec": window_sec, "bbox": bbox}

    if error:
        return {"ok": False, "error": f"AIS 服务端错误: {error}", "total": 0,
                "window_sec": window_sec, "bbox": bbox}

    return _aggregate(positions, statics, msg_count, window_sec, bbox)


if __name__ == "__main__":
    # 本地调试：python hormuz.py —— 采样并打印 JSON 统计
    stats = collect_hormuz_traffic()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
