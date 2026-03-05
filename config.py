import os

# ── 敏感信息：必须从环境变量读取 ──
FEISHU_WEBHOOK  = os.environ["FEISHU_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ["OPENAI_MODEL"]       # ← 改为强制读取
SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_KEY"]

# ── 市场 Slug 列表：从环境变量读取，逗号分隔 ──
SLUGS = [s.strip() for s in os.environ["MARKET_SLUGS"].split(",")]

# ── 历史快照配置 ──
HISTORY_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
MAX_SNAPSHOTS = 1440
