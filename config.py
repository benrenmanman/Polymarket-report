import os

# ── 敏感信息：从环境变量读取 ──
WECOM_WEBHOOK   = os.environ["WECOM_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ["OPENAI_MODEL"]

# ── 市场 Slug 列表 ──
SLUGS = [s.strip().strip("\n").strip("\r") for s in os.environ["MARKET_SLUGS"].split(",") if s.strip()]

# 删除内容：
# - SUPABASE_URL / SUPABASE_KEY  （不再写数据库）
# - HISTORY_FILE / MAX_SNAPSHOTS （不再本地存储）
