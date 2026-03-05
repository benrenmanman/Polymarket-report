import os

HISTORY_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
MAX_SNAPSHOTS = 1440

FEISHU_WEBHOOK  = os.environ["FEISHU_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
SLUGS           = os.environ.get("MARKET_SLUGS", "what-price-will-bitcoin-hit-in-2025").split(",")
