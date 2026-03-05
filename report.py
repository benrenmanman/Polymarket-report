import requests
import json
import os
from datetime import datetime, timezone

# ── 环境变量 ──────────────────────────────────────────────
FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
SLUGS = os.environ.get(
    "MARKET_SLUGS",
    "bitcoin-price-eoy"
).split(",")


# ── 1. 拉取 Polymarket 数据 ───────────────────────────────
def fetch_market(slug: str) -> dict:
    slug = slug.strip()
    
    # 先试 events 端点
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    print(f"events 端点返回：{json.dumps(data, ensure_ascii=False, indent=2)}")
    
    if data:
        return data[0]
    
    # 如果空，再试 markets 端点
    url2 = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    resp2 = requests.get(url2, timeout=30)
    resp2.raise_for_status()
    data2 = resp2.json()
    print(f"markets 端点返回：{json.dumps(data2, ensure_ascii=False, indent=2)}")
    
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


# ── 3. 格式化为可读文本 ───────────────────────────────────
def format_report(info: dict) -> str:
    lines = []
    lines.append(f"**📌 {info['title']}**")
    lines.append(f"**💰 总交易量**：{info['volume_total_M']}M　｜　**近7日**：{info['volume_1wk_M']}M")
    lines.append("")

    for m in info["markets"]:
        lines.append(f"**❓ {m['question']}**")
        for option, price in m["options"].items():
            pct = round(float(price) * 100, 1)
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(f"- {option}：{bar} **{pct}%**")
        lines.append(f"  交易量：{m['volume_M']}M")
        lines.append("")

    return "\n".join(lines)


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

    if result.get("code") != 0 and result.get("StatusCode") != 0:
        raise Exception(f"飞书推送失败：{result}")


# ── 5. 主流程 ─────────────────────────────────────────────
def main():
    messages = []

    for slug in SLUGS:
        try:
            raw    = fetch_market(slug)
            print(json.dumps(raw, ensure_ascii=False, indent=2))  # ← 加这行
            info   = extract_key_info(raw)
            report = format_report(info)
            messages.append(report)
            print(f"✅ {slug} 处理成功")
        except Exception as e:
            messages.append(f"⚠️ `{slug}` 获取失败：{e}")
            print(f"❌ {slug} 出错：{e}")

    final_text = "\n\n---\n\n".join(messages)
    send_feishu(final_text)
    print("✅ 飞书推送成功")


if __name__ == "__main__":
    main()
