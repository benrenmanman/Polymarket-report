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
def ai_analyze(info: dict) -> str:
    prompt = f"""
你是一位专业的预测市场分析师。以下是来自 Polymarket 的市场数据，请用中文撰写一份简洁的播报分析。

市场数据：
{json.dumps(info, ensure_ascii=False, indent=2)}

要求：
1. 用 **Markdown 格式** 输出，适合在飞书消息卡片中展示
2. 包含以下内容：
   - 📌 市场标题 + 当前最高概率选项
   - 📊 各选项概率（用进度条 █ 表示）
   - 💡 简短的市场解读（2~3句话，分析市场情绪和可能原因）
   - 💰 交易量数据
3. 语言简洁专业，避免废话
4. 不要输出代码块，直接输出 Markdown 文本
"""

    # ── 防御性检查 ──
    if not isinstance(client, OpenAI):
        raise Exception(f"client 类型异常：{type(client)}，请检查 OPENAI_BASE_URL 和 OPENAI_API_KEY")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是专业的预测市场分析师，擅长解读 Polymarket 数据并给出简洁有价值的市场洞察。"},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.7,
        max_tokens=800,
    )

    # ── 确认返回类型 ──
    if not hasattr(response, "choices"):
        raise Exception(f"OpenAI 返回类型异常：{type(response)}，内容：{response}")

    return response.choices[0].message.content.strip()


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

# ── 5. 读取并存储数据 ───────────────────────────────────
HISTORY_FILE = "history.json"

def load_history() -> dict:
    """读取上次的历史数据"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(data: dict):
    """保存本次数据到历史文件"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── 6. 对比历史数据，计算变化趋势 ───────────────────────────────────
def calc_trend(slug: str, current: dict, history: dict) -> dict:
    """对比历史数据，计算变化趋势"""
    trend = {}
    prev = history.get(slug)

    if not prev:
        trend["status"] = "首次记录，暂无趋势数据"
        return trend

    trend["time_diff"] = f"距上次更新：{prev.get('timestamp', '未知')}"
    trend["changes"] = []

    # 对比每个选项的概率变化
    curr_outcomes = {o["title"]: o["probability"] for o in current.get("outcomes", [])}
    prev_outcomes = {o["title"]: o["probability"] for o in prev.get("outcomes", [])}

    for title, curr_prob in curr_outcomes.items():
        prev_prob = prev_outcomes.get(title, curr_prob)
        delta = round(curr_prob - prev_prob, 4)
        arrow = "📈" if delta > 0.01 else ("📉" if delta < -0.01 else "➡️")
        trend["changes"].append({
            "option": title,
            "prev":    f"{prev_prob*100:.1f}%",
            "current": f"{curr_prob*100:.1f}%",
            "delta":   f"{delta*100:+.1f}%",
            "arrow":   arrow
        })

    # 交易量变化
    curr_vol = current.get("volume", 0)
    prev_vol = prev.get("volume", 0)
    trend["volume_delta"] = f"{curr_vol - prev_vol:+.0f} USDC"

    return trend


# ── 5. 主流程 ─────────────────────────────────────────────
def main():
    messages = []

    for slug in SLUGS:
        try:
            raw    = fetch_market(slug)
            info   = extract_key_info(raw)
            report = ai_analyze(info)
            messages.append(report)
            print(f"✅ {slug} 处理成功")
        except Exception as e:
            messages.append(f"⚠️ `{slug}` 处理失败：{e}")
            print(f"❌ {slug} 出错：{e}")

    final_text = "\n\n---\n\n".join(messages)
    send_feishu(final_text)
    print("✅ 飞书推送成功")


if __name__ == "__main__":
    main()
