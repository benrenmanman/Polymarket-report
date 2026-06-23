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

## 霍尔木兹海峡通行情况跟踪（基于 aisstream.io）
定期报告可附带一段**霍尔木兹海峡实时通行态势**，数据来自 [aisstream.io](https://aisstream.io/) 的实时 AIS 推流。
每次运行会连接 AIS WebSocket、采样海峡边界框内的船舶位置报文，聚合为：
在区船舶数、航行中/锚泊数、进出湾流向（东行出湾 / 西行入湾）、平均航速、船型构成（油轮/货船等）、重点油轮动向，并由 AI 给出形势研判，随报告一同推送。

### 启用方式
1. 在 [aisstream.io/apikeys](https://aisstream.io/apikeys) 申请 API Key；
2. Settings→Secrets and variables→Actions→新增 `AISSTREAM_API_KEY`（填入你的 Key）。
   **未配置时该模块自动跳过，不影响 Polymarket 主报告。**

### 可选配置
- `HORMUZ_WINDOW_SEC`（Secret，单次采样秒数，默认 60）。窗口越长覆盖船舶越全。
- 监测边界框 `HORMUZ_BBOX` 在 `config.py` 中定义，默认 `[[25.5, 55.5], [27.0, 57.3]]`
  （格式 `[[南纬, 西经], [北纬, 东经]]`，覆盖海峡主航道与进出港通道）。

### 本地调试
```bash
AISSTREAM_API_KEY=你的key python hormuz.py   # 采样并打印 JSON 统计
```
