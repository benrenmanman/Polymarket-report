import requests
import json
import os
from datetime import datetime, timezone

# ── 环境变量（从 GitHub Secrets 注入，本地测试时可改为直接赋值）──
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
SLUGS = os.environ.get(
    "MARKET_SLUGS",
    "fed-decision-in-october"
).split(",")


# ── 1. 拉取 Polymarket 数据 ───────────────────────────────
def fetch_market(slug: str) -> dict:
    url = f"https://gamma-api.polymarket.com/events?slug={slug.strip()}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else {}


# ── 2. 提取关键字段（减少 AI token 消耗）─────────────────
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


# ── 3. 调用 AI 生成中文摘要 ───────────────────────────────
def ask_ai(info: dict) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
你是金融市场分析助手。以下是 Polymarket 预测市场的最新数据（volume 单位：百万美元）：

{json.dumps(info, ensure_ascii=False, indent=2)}

请用中文输出简洁播报，格式如下：
**📌 市场名称**：xxx
**📊 各选项概率**：
- 选项A：xx%
- 选项B：xx%
**💰 交易量**：总量 xxM / 近7日 xxM
**📈 市场情绪**：一句话总结
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
    )
    return resp.choices[0].message.content.strip()


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
                    "content": "📊 Polymarket 定时播报"
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

    # 飞书返回 code=0 或 StatusCode=0 表示成功
    if result.get("code") != 0 and result.get("StatusCode") != 0:
        raise Exception(f"飞书推送失败：{result}")


# ── 5. 主流程 ─────────────────────────────────────────────
def main():
    messages = []

    for slug in SLUGS:
        try:
            raw     = fetch_market(slug)
            info    = extract_key_info(raw)
            summary = ask_ai(info)
            messages.append(summary)
            print(f"✅ {slug} 处理成功")
        except Exception as e:
            messages.append(f"⚠️ `{slug}` 获取失败：{e}")
            print(f"❌ {slug} 出错：{e}")

    final_text = "\n\n---\n\n".join(messages)
    send_feishu(final_text)
    print("✅ 飞书推送成功")


if __name__ == "__main__":
    main()
