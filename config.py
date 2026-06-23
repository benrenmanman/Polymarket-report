import os
import re


def _int_env(name: str, default: int) -> int:
    """
    读取整数型环境变量；未设置 / 为空串 / 非法值时回退到 default。
    注：GitHub Actions 在引用了不存在的 Secret 时，会把对应 env 设为
    空字符串（而非不设置），直接 int("") 会抛 ValueError，故统一兜底。
    """
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


# ── 敏感信息：从环境变量读取 ──
WECOM_WEBHOOK   = os.environ["WECOM_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ["OPENAI_MODEL"]

# ── 企业微信应用消息 API（可选，用于发送 mpnews 图文消息）──
# 若未配置，则保持原有群机器人 Webhook 推送方式。
CORP_ID     = os.environ.get("CORP_ID", "")
CORP_SECRET = os.environ.get("CORP_SECRET", "")
AGENT_ID    = _int_env("AGENT_ID", 0)
# 三项均配置时启用 mpnews（将所有内容打包为一篇图文）
MPNEWS_ENABLED = bool(CORP_ID and CORP_SECRET and AGENT_ID)

# ── 市场 Slug 列表 ──
# 支持逗号、换行（含 \r\n）混合分隔，便于多行 Secret 配置。
SLUGS = [s.strip() for s in re.split(r"[,\r\n]+", os.environ["MARKET_SLUGS"]) if s.strip()]

# ── 霍尔木兹海峡 AIS 通行跟踪（aisstream.io，可选）──
# 配置 AISSTREAM_API_KEY 后，定期报告会附带一段海峡实时通行态势。
# 申请地址：https://aisstream.io/apikeys
# .strip() 兜底 Secret 末尾可能混入的换行/空白，避免破坏 WebSocket 鉴权。
AISSTREAM_API_KEY = os.environ.get("AISSTREAM_API_KEY", "").strip()
HORMUZ_ENABLED    = bool(AISSTREAM_API_KEY)
# 单次采样时长（秒）。aisstream 为实时推流，窗口越长覆盖船舶越全。
# 用 _int_env 兜底：未配置该可选 Secret 时 GitHub Actions 传入空串。
HORMUZ_WINDOW_SEC = _int_env("HORMUZ_WINDOW_SEC", 60)
# 边界框：[[南纬, 西经], [北纬, 东经]]，覆盖霍尔木兹海峡主航道与进出港通道。
# 西接波斯湾（霍尔木兹岛/格什姆岛一带），东连阿曼湾。
HORMUZ_BBOX = [[25.5, 55.5], [27.0, 57.3]]

# 删除内容：
# - SUPABASE_URL / SUPABASE_KEY  （不再写数据库）
# - HISTORY_FILE / MAX_SNAPSHOTS （不再本地存储）
