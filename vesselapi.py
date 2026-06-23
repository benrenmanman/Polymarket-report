"""
基于 VesselAPI（https://vesselapi.com/）REST 接口的霍尔木兹海峡通行采样。

相比 hormuz.py（aisstream 实时 WebSocket 流），VesselAPI 是 REST 接口：
一次请求即可拿到边界框内"当前"全部船舶，更适合定期一次性任务，
商用数据覆盖通常也更全。返回结构与 hormuz.collect_hormuz_traffic 完全一致
（复用 _aggregate），因此分析 / 推送 / 历史累积模块可直接沿用。

鉴权：Authorization: Bearer <KEY>。支持配置多把 key（VESSELAPI_KEYS），
运行时按序故障切换（配额叠加 + 冗余）。API Key 不写入源码，从环境变量读取。

参考：
  GET /v1/location/vessels/bounding-box
      ?filter.latBottom=&filter.latTop=&filter.lonLeft=&filter.lonRight=
      &pagination.limit=
  → {"data": [{mmsi, vesselName, latitude, longitude, sog, cog, heading,
               navStatus, shipType, destination, timestamp}, ...],
     "pagination": {"nextToken": "..."}}
"""
import time
import requests

from config import VESSELAPI_KEYS, HORMUZ_BBOX, HORMUZ_FALLBACK_BBOX
from hormuz import _aggregate, _clean

VESSELAPI_BASE  = "https://api.vesselapi.com/v1"
_BBOX_ENDPOINT  = f"{VESSELAPI_BASE}/location/vessels/bounding-box"
_PAGE_LIMIT     = 50    # VesselAPI 上限：pagination.limit 不得超过 50
_MAX_PAGES      = 30    # 配合每页 50，最多取 1500 条，兼顾覆盖与配额消耗
_TIMEOUT        = 20


def _get(d: dict, names: list, default=None):
    """从 dict 中按候选字段名（兼容 camelCase / snake_case）取第一个非空值。"""
    for n in names:
        v = d.get(n)
        if v is not None:
            return v
    return default


def _request_page(params: dict, keys: list):
    """
    用一组 key 依次尝试请求一页（鉴权/限流失败时切换下一把 key）。
    返回 (json_or_None, error_or_None)。
    """
    last_err = None
    for key in keys:
        try:
            resp = requests.get(
                _BBOX_ENDPOINT,
                params=params,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
        except Exception as e:
            last_err = f"请求异常: {e}"
            continue

        if resp.status_code == 200:
            try:
                return resp.json(), None
            except Exception as e:
                return None, f"响应解析失败: {e}"
        if resp.status_code in (401, 403):
            last_err = f"鉴权失败(HTTP {resp.status_code})"
            continue   # 换下一把 key
        if resp.status_code == 429:
            # 配额耗尽 / 限流：尊重 Retry-After（封顶 3s）后切换下一把 key
            ra = resp.headers.get("Retry-After", "1")
            try:
                time.sleep(min(float(ra), 3))
            except (TypeError, ValueError):
                time.sleep(1)
            last_err = "限流或配额耗尽(HTTP 429)"
            continue
        # 其它状态码：直接返回错误（截断正文以免噪音）
        return None, f"HTTP {resp.status_code}: {resp.text[:160]}"
    return None, last_err or "无可用 API Key"


def _fetch_bbox(bbox: list, keys: list):
    """
    拉取一个边界框内的全部船舶（翻页直到无 nextToken 或达页数上限）。
    返回 (records, error)；error 非空且 records 为空表示彻底失败。
    """
    lat_bottom, lon_left = bbox[0]
    lat_top,    lon_right = bbox[1]
    base = {
        "filter.latBottom": lat_bottom,
        "filter.latTop":    lat_top,
        "filter.lonLeft":   lon_left,
        "filter.lonRight":  lon_right,
        "pagination.limit": _PAGE_LIMIT,
    }

    records: list = []
    token = None
    seen_tokens: set = set()

    for _ in range(_MAX_PAGES):
        params = dict(base)
        if token:
            params["pagination.nextToken"] = token
        payload, err = _request_page(params, keys)
        if err:
            return records, err
        rows = payload.get("data") or payload.get("vessels") or []
        records.extend(rows)
        token = (payload.get("pagination") or {}).get("nextToken")
        if not token or token in seen_tokens:
            break
        seen_tokens.add(token)

    return records, None


def _to_positions_statics(records: list):
    """把 VesselAPI 船舶记录映射为 _aggregate 所需的 positions / statics 结构。"""
    positions: dict = {}
    statics: dict = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        mmsi = _get(r, ["mmsi", "MMSI", "userId"])
        if mmsi is None:
            continue
        name = _clean(_get(r, ["vesselName", "vessel_name", "name", "shipName"]))
        positions[mmsi] = {
            "mmsi": mmsi,
            "name": name,
            "sog":  _get(r, ["sog", "SOG", "speed", "speedOverGround"]),
            "cog":  _get(r, ["cog", "COG", "course", "courseOverGround"]),
            "nav":  _get(r, ["navStatus", "nav_status", "navigationalStatus"]),
        }
        statics[mmsi] = {
            "type":        _get(r, ["shipType", "ship_type", "vesselType",
                                    "vessel_type", "type", "aisShipType"]),
            "name":        name,
            "destination": _clean(_get(r, ["destination", "dest"], "")),
        }
    return positions, statics


def collect_hormuz_traffic_vesselapi(bbox: list | None = None) -> dict:
    """
    通过 VesselAPI 拉取霍尔木兹海峡当前通行情况，返回与 aisstream 版一致的统计 dict。
    海峡边界框无返回时，回退「波斯湾—阿曼湾」大区再查一次（与 aisstream 版同策略）。
    """
    if not VESSELAPI_KEYS:
        return {"ok": False, "error": "未配置 VESSELAPI_KEYS", "total": 0,
                "source": "vesselapi"}

    use_default = bbox is None
    primary = bbox or HORMUZ_BBOX

    records, err = _fetch_bbox(primary, VESSELAPI_KEYS)
    if err and not records:
        return {"ok": False, "error": f"VesselAPI 请求失败: {err}", "total": 0,
                "source": "vesselapi", "bbox": primary}

    used_bbox, area = primary, "strait"
    if not records and use_default:
        print("[vesselapi] 海峡边界框无返回，回退波斯湾—阿曼湾大区……")
        fb_records, _fb_err = _fetch_bbox(HORMUZ_FALLBACK_BBOX, VESSELAPI_KEYS)
        if fb_records:
            records, used_bbox, area = fb_records, HORMUZ_FALLBACK_BBOX, "wide"

    positions, statics = _to_positions_statics(records)
    stats = _aggregate(positions, statics, msg_count=len(records),
                       window_sec=0, bbox=used_bbox)
    stats["area"]   = area
    stats["source"] = "vesselapi"
    return stats


if __name__ == "__main__":
    import json
    print(json.dumps(collect_hormuz_traffic_vesselapi(), ensure_ascii=False, indent=2))
