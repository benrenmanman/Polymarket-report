# polymarket-report/

### 该项目可用于将Polymarket中不同赌注的最新进展定时发送至飞书/企微

## 修改Ai模型？
Settings→Secrets and variables→Actions→OPENAI_MODEL（默认gpt-4o-mini）
## 修改Ploymarket观测市场？
Settings→Secrets and variables→Actions→MARKET_SLUGS（Slugs之间逗号分隔）
## 调换API来源？
1. Settings→Secrets and variables→Actions→OPENAL_API_KEY（更改新API）
2. Settings→Secrets and variables→Actions→OPENAL_BASE_URL（同步更换base url）
## 更改飞书/企微的Webhook？
1. 修改report.py中的`send_feishu()`函数，并更改相应函数调用
2. Settings→Secrets and variables→Actions→FEISHU_WEBHOOK（更新webhook）
## 更改Ai的Prompt？
修改report.py中的`ai_analyze()`函数
## 更改定时发送时间？
修改report.yml中的函数：
```
on:
  # 定时触发（UTC 时间）
  # 以下配置 = 北京时间 每天 09:00 / 15:00 / 21:00
  schedule:
- cron: '*/30 * * * *'
```
