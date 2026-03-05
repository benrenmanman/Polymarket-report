import json
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

def ai_analyze(info: dict, trend: dict) -> str:
    count       = trend.get("count", 0)
    comparisons = trend.get("comparisons", {})

    if count < 2:
        trend_block = "首次记录，无历史趋势。"
    else:
        available   = list(comparisons.keys())
        trend_block = f"""
历史快照数：{count} 条，可对比维度：{', '.join(available)}
{json.dumps(comparisons, ensure_ascii=False, indent=2)}
"""

    prompt = f"""
你是预测市场播报助手，请基于以下数据生成一条简洁播报卡片，禁止编造数据。

【市场数据】
{json.dumps(info, ensure_ascii=False, indent=2)}

【趋势数据】
{trend_block}

输出格式（严格按此结构，不加多余说明）：

📌 **[市场标题]**
🏆 领先：[最高概率选项] [概率]%

📊 概率
[选项A] [概率]% [↑/↓/—][变化幅度，无历史则省略]
[选项B] [概率]% [↑/↓/—][变化幅度，无历史则省略]
（变化超过5%加⚠️）

💰 交易量：[总量或各维度简述，一行内]
💡 [市场情绪一句话判断]
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是预测市场播报助手，输出必须简洁，每条播报不超过10行。"},
            {"role": "user",   "content": prompt}
        ],
        max_completion_tokens=400,  # 单条压缩到400 token，多条不撑屏
    )

    message = response.choices[0].message
    if getattr(message, "refusal", None):
        return "⚠️ 模型拒绝输出"
    return (message.content or "").strip()
