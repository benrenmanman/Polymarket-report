import requests
import json
import os
from datetime import datetime, timezone
from openai import OpenAI

# ── 必须先读环境变量，再初始化 client ──
FEISHU_WEBHOOK  = os.environ["FEISHU_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
SLUGS = os.environ.get("MARKET_SLUGS", "what-price-will-bitcoin-hit-in-2025").split(",")

# ── 读完变量之后才能初始化 client ──
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# ── 1. 拉取 Polymarket 数据 ───────────────────────────────
def fetch_market(slug: str) -> dict:
    slug = slug.strip()
    url  = f"https://gamma-api.polymarket.com/events?slug={slug}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data:
        return data[0]

    url2  = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    resp2 = requests.get(url2, timeout=30)
    resp2.raise_for_status()
    data2 = resp2.json()
    return data2[0] if data2 else {}

# ── 2. 提取关键字段 ───────────────────────────────────────
def extract_key_info(raw: dict) -> dict:
    markets = []
    for m in raw.get("markets", []):
        outcomes = json.loads(m.get("outcomes", "[]"))
        prices   = json.loads(m.get("outcomePrices", "[]"))
        markets.append({
            "question": m.get("question"),
            "options":  dict(zip(outcomes, prices)),
            "volume_M": round(m.get("volumeNum", 0) / 1e6, 2),
            "closed":   m.get("closed"),
        })
    return {
        "title":          raw.get("title"),
        "closed":         raw.get("closed"),
        "volume_total_M": round(raw.get("volume", 0) / 1e6, 2),
        "volume_1wk_M":   round(raw.get("volume1wk", 0) / 1e6, 2),
        "markets":        markets,
    }

# ── 3. AI 分析 ────────────────────────────────────────────
def ai_analyze(info: dict, trend: dict) -> str:
    count = trend.get("count", 0)
    comparisons = trend.get("comparisons", {})

    # 动态生成趋势说明
    if count < 2:
        trend_block = "⚠️ 首次记录，暂无历史趋势，禁止编造任何对比数据。"
    else:
        available = list(comparisons.keys())
        trend_block = f"""
以下是基于真实历史快照的趋势数据（共 {count} 条记录），
可用对比维度：{', '.join(available)}

{json.dumps(comparisons, ensure_ascii=False, indent=2)}

⚠️ 只能使用以上维度进行对比，不得提及不存在的时间维度。
"""

    prompt = f"""
你是专业预测市场分析师，请严格基于以下数据撰写播报，禁止编造数据。

【当前市场数据】
{json.dumps(info, ensure_ascii=False, indent=2)}

【趋势对比数据】
{trend_block}

输出格式（Markdown）：
1. 📌 市场标题 + 当前最高概率选项
2. 📊 各选项概率
3. 📈 趋势分析：
   - 有哪些维度的数据就分析哪些，没有的不提
   - 变化超过 5% 的选项重点标注 ⚠️
4. 💡 市场情绪判断（2~3句）
5. 💰 各维度交易量变化
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是专业预测市场分析师，只基于提供的数据分析，不编造任何数字。"},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1200,
    )
    return response.choices[0].message.content.strip()

# ── 5. 读取并存储数据 ───────────────────────────────────
def load_history() -> dict:
    """
    读取 history.json。
    文件不存在时返回空字典，结构损坏时打印警告并返回空字典。
    """
    if not os.path.exists(HISTORY_FILE):
        print("📂 history.json 不存在，将创建新文件")
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"📂 已加载历史数据，共 {len(data)} 个市场")
        return data
    except json.JSONDecodeError as e:
        print(f"⚠️ history.json 解析失败：{e}，将重置为空")
        return {}

# ─────────────────────────────────────────────
# 2. 历史数据：精简快照构建
# ─────────────────────────────────────────────
def build_snapshot(info: dict) -> dict:
    """
    从完整 API 数据中提取精简快照，过滤已关闭/归档的子市场。
    outcomePrices 兼容字符串数组和字典两种格式。
    """
    active_markets = [
        m for m in info.get("markets", [])
        if not m.get("archived", False) and not m.get("closed", False)
    ]

    markets_snapshot = []
    for m in active_markets:
        # outcomePrices 可能是 JSON 字符串 "[\"0.31\", \"0.69\"]" 或已解析的字典
        raw_prices = m.get("outcomePrices", "[]")
        if isinstance(raw_prices, str):
            try:
                prices_list = json.loads(raw_prices)
                outcome_prices = {
                    "Yes": float(prices_list[0]),
                    "No":  float(prices_list[1])
                }
            except Exception:
                outcome_prices = {}
        elif isinstance(raw_prices, dict):
            outcome_prices = raw_prices
        else:
            outcome_prices = {}

        markets_snapshot.append({
            "id":                  m.get("id", ""),
            "question":            m.get("question", ""),
            "slug":                m.get("slug", ""),
            "active":              m.get("active", False),
            "closed":              m.get("closed", False),
            "outcomePrices":       outcome_prices,
            "volume":              m.get("volumeNum",      m.get("volume", 0)),
            "volume24hr":          m.get("volume24hr",     0),
            "lastTradePrice":      m.get("lastTradePrice", 0),
            "bestBid":             m.get("bestBid",        0),
            "bestAsk":             m.get("bestAsk",        0),
            "oneDayPriceChange":   m.get("oneDayPriceChange",   None),
            "oneWeekPriceChange":  m.get("oneWeekPriceChange",  None),
            "oneMonthPriceChange": m.get("oneMonthPriceChange", None),
        })

    return {
        "timestamp":  info.get("timestamp", ""),
        "volume":     info.get("volume",     0),
        "volume24hr": info.get("volume24hr", 0),
        "markets":    markets_snapshot,
    }

# ─────────────────────────────────────────────
# 3. 历史数据：追加快照
# ─────────────────────────────────────────────
def append_snapshot(history: dict, slug: str, info: dict) -> dict:
    """
    把本次精简快照追加到 history[slug] 数组末尾。
    超过 MAX_SNAPSHOTS 时自动裁剪最旧的记录。
    """
    if slug not in history:
        history[slug] = []

    history[slug].append(build_snapshot(info))

    if len(history[slug]) > MAX_SNAPSHOTS:
        history[slug] = history[slug][-MAX_SNAPSHOTS:]
        print(f"✂️  {slug} 历史超过 {MAX_SNAPSHOTS} 条，已裁剪旧数据")

    return history

# ─────────────────────────────────────────────
# 4. 历史数据：保存
# ─────────────────────────────────────────────
def save_history(history: dict):
    """
    将完整历史写回 history.json。
    先写临时文件再原子替换，防止写入中断导致文件损坏。
    """
    tmp_file = HISTORY_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, HISTORY_FILE)
        total = sum(len(v) for v in history.values())
        print(f"💾 history.json 已保存，共 {len(history)} 个市场 / {total} 条快照")
    except Exception as e:
        print(f"❌ 保存 history.json 失败：{e}")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


# ── 6. 对比历史数据，计算变化趋势 ───────────────────────────────────
def calc_trend(slug: str, history: dict) -> dict:
    """从历史时间轴提取多维度趋势"""
    snapshots = history.get(slug, [])
    count = len(snapshots)
    
    if count < 2:
        return {"status": "首次记录，暂无趋势数据", "count": count}

    trend = {"count": count, "comparisons": {}}
    latest = snapshots[-1]

    # 定义对比维度：名称 → 往前取第几条
    intervals = {}
    if count >= 2:   intervals["30分钟前"] = snapshots[-2]
    if count >= 48:  intervals["24小时前"] = snapshots[-48]
    if count >= 336: intervals["7天前"]   = snapshots[-336]
    if count >= 1440:intervals["30天前"]  = snapshots[-1440]

    latest_probs = {o["title"]: o["probability"] for o in latest["outcomes"]}

    for label, old_snap in intervals.items():
        old_probs = {o["title"]: o["probability"] for o in old_snap["outcomes"]}
        changes = []
        for title, curr_prob in latest_probs.items():
            old_prob = old_probs.get(title, curr_prob)
            delta = round(curr_prob - old_prob, 4)
            arrow = "📈" if delta > 0.01 else ("📉" if delta < -0.01 else "➡️")
            changes.append({
                "option":  title,
                "old":     f"{old_prob*100:.1f}%",
                "current": f"{curr_prob*100:.1f}%",
                "delta":   f"{delta*100:+.1f}%",
                "arrow":   arrow
            })
        
        vol_delta = latest["volume"] - old_snap["volume"]
        trend["comparisons"][label] = {
            "from_timestamp": old_snap["timestamp"],
            "changes":        changes,
            "volume_delta":   f"{vol_delta:+.0f} USDC"
        }

    return trend

# ── 4. 推送飞书消息卡片 ───────────────────────────────────
def send_feishu(text: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📊 Polymarket AI 播报"
                },
                "template": "blue"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": text
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "markdown",
                        "content": f"🕐 更新时间：{now}"
                    }
                ]
            }
        }
    }

    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()

    if result.get("code") != 0 and result.get("StatusCode") != 0:
        raise Exception(f"飞书推送失败：{result}")


# ── 5. 主流程 ─────────────────────────────────────────────
def main():
    history = load_history()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    results = []

    for slug in SLUGS:
        slug = slug.strip()
        try:
            info = fetch_market(slug)
            info["timestamp"] = timestamp

            # 先计算趋势（用追加前的历史）
            trend = calc_trend(slug, history)

            # 再追加本次快照
            history = append_snapshot(history, slug, info)

            analysis = ai_analyze(info, trend)
            results.append(analysis)
            print(f"✅ {slug} 处理完成（历史共 {len(history[slug])} 条）")
        except Exception as e:
            print(f"⚠️ {slug} 处理失败：{e}")

    if results:
        full_report = "\n\n---\n\n".join(results)
        send_feishu(f"📊 **Polymarket 市场播报** `{timestamp}`\n\n{full_report}")

    # 保存追加后的完整历史
    save_history(history)

main()
