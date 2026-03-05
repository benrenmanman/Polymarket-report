import json
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

def ai_analyze(info: dict, trend: dict) -> str:
    comparisons = trend.get("comparisons", {})

    if not comparisons:
        snapshot_block = "首次记录，无历史数据。"
    else:
        snapshot_block = json.dumps(comparisons, ensure_ascii=False, indent=2)

    prompt = f"""
你是预测市场数据播报助手。
你的唯一任务是：将以下原始数据翻译为中文并按格式排列输出。
严禁添加任何主观判断、情绪分析、趋势解读或预测性语言。

【各时间节点快照数据】
{snapshot_block}

输出格式（严格按此结构，缺少的时间节点直接省略，不加说明）：

📌 **[市场标题（中文）]**

| 时间节点 | [选项A（中文）] | [选项B（中文）] | … |
|----------|----------------|----------------|---|
| 最新     | [概率]%        | [概率]%        | … |
| 上次     | [概率]%        | [概率]%        | … |
| 上周同期 | [概率]%        | [概率]%        | … |
| 上月同期 | [概率]%        | [概率]%        | … |

💰 交易量（最新）：[数值，一行内]
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": (
                "你是预测市场数据播报助手。"
                "只输出数据本身，禁止任何主观判断、情绪词汇、趋势解读。"
                "所有市场标题和选项名称翻译为中文。"
                "输出不超过15行。"
            )},
            {"role": "user", "content": prompt}
        ],
        max_completion_tokens=500,
    )

    message = response.choices[0].message
    if getattr(message, "refusal", None):
        return "⚠️ 模型拒绝输出"
    return (message.content or "").strip()
