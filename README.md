# polymarket-report/
## 修改Ai模型？
Settings→Secrets and variables→Actions→OPENAI_MODEL（默认gpt-4o-mini）
补充Ploymarket观测市场？
Settings→Secrets and variables→Actions→MARKET_SLUGS（Slugs之间逗号分隔）
## 调换API来源？
①	Settings→Secrets and variables→Actions→OPENAL_API_KEY（更改新API）
// ②	Settings→Secrets and variables→Actions→OPENAL_BASE_URL（同步更换base url）
## 更改飞书/企微的Webhook？
①	修改report.py中的send_feishu()函数
// ②	Settings→Secrets and variables→Actions→FEISHU_WEBHOOK（更新webhook）
## 更改定时发送时间？
修改report.yml中的函数：
on:
  #### 定时触发（UTC 时间）
  #### 以下配置 = 北京时间 每天 09:00 / 15:00 / 21:00
  schedule:
- cron: '*/30 * * * *'
