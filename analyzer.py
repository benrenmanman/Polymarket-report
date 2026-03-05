def ai_analyze(info: dict, trend: dict) -> str:
    count       = trend.get("count", 0)
    comparisons = trend.get("comparisons", {})

    if count < 2:
        trend_block = "⚠️ 首次记录，暂无历史趋势，禁止编造任何对比数据。"
    else:
        available   = list(comparisons.keys())
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
3. 📈 趋势分析
4. 💡 市场情绪判断（2~3句）
5. 💰 各维度交易量变化
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是专业预测市场分析师，只基于提供的数据分析，不编造任何数字。"},
            {"role": "user",   "content": prompt}
        ],
        max_completion_tokens=1200,   # ✅ 兼容新模型
    )

    message = response.choices[0].message

    # ✅ 处理模型拒绝的情况
    if getattr(message, "refusal", None):
        print(f"⚠️ 模型拒绝回答：{message.refusal}")
        return ""

    return (message.content or "").strip()
