import os

# ── 敏感信息：必须从环境变量读取 ──
FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

# ── 非敏感配置：直接写在代码里，Actions 无需配置 ──
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")
SLUGS = os.environ.get(
    "MARKET_SLUGS",
    "us-x-iran-ceasefire-by,us-forces-enter-iran-by,will-iran-name-a-successor-to-khamenei-by"  # 直接在这里维护
).split(",")

# ── 历史快照配置 ──
HISTORY_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
MAX_SNAPSHOTS = 1440
