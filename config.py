import os

# ── 敏感信息：从环境变量读取 ──
WECOM_WEBHOOK   = os.environ["WECOM_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ["OPENAI_MODEL"]

# ── 企业微信应用消息 API（可选，用于发送 mpnews 图文消息）──
# 若未配置，则保持原有群机器人 Webhook 推送方式。
CORP_ID     = os.environ.get("CORP_ID", "")
CORP_SECRET = os.environ.get("CORP_SECRET", "")
AGENT_ID    = int(os.environ.get("AGENT_ID", "0"))
# 三项均配置时启用 mpnews（将所有内容打包为一篇图文）
MPNEWS_ENABLED = bool(CORP_ID and CORP_SECRET and AGENT_ID)

# ── 市场 Slug 列表 ──
SLUGS = [s.strip().strip("\n").strip("\r") for s in os.environ["MARKET_SLUGS"].split(",") if s.strip()]

# 删除内容：
# - SUPABASE_URL / SUPABASE_KEY  （不再写数据库）
# - HISTORY_FILE / MAX_SNAPSHOTS （不再本地存储）
