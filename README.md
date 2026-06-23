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

## 霍尔木兹海峡通行情况跟踪
定期报告可附带一段**霍尔木兹海峡通行态势**，聚合为：
在区船舶数、航行中/锚泊数、进出湾流向（东行出湾 / 西行入湾）、平均航速、船型构成（油轮/货船等）、重点油轮动向、过去 24h 趋势，并由 AI 给出形势研判，随报告一同推送。

### 两种数据源（二选一）
| 数据源 | 接口 | 特点 | 配置 Secret |
|---|---|---|---|
| **VesselAPI**（推荐） | REST，一次请求取边界框内当前全部船舶 | 商用、覆盖更全、含船型字段 | `VESSELAPI_KEYS`（可填多把 key，逗号分隔，自动故障切换 + 配额叠加） |
| **aisstream.io** | 实时 WebSocket 流，监听固定窗口采样 | 免费，但众包岸基覆盖在部分海域有限 | `AISSTREAM_API_KEY` |

- 用 `HORMUZ_SOURCE`（Secret）显式指定 `vesselapi` / `aisstream`；**留空则自动择优**：有 VesselAPI key 用 VesselAPI，否则用 aisstream，都没有则跳过该模块。
- 两种源返回结构一致，趋势累积 / AI 研判 / 卡片推送逻辑完全共用。
- VesselAPI 申请：[vesselapi.com](https://vesselapi.com/)；文档 [/docs](https://vesselapi.com/docs)、[/api-reference](https://vesselapi.com/api-reference)。
  - 接口：`GET /v1/location/vessels/bounding-box`，鉴权 `Authorization: Bearer <key>`。
  - 注意 429 限流（配额耗尽 / 并发>20），可选 `time.from`/`time.to` 支持最近 4h 历史窗口。

### 取数逻辑（重要）
aisstream 是**实时 WebSocket 推流**，不是"查一次返回当前所有船"的接口。因此本模块的做法是：
连接后**持续监听 `HORMUZ_WINDOW_SEC`（默认 60）秒**，收集这段时间内推送过来的报文，按 MMSI 去重后聚合——本质是一次"**采样快照**"，只统计窗口内播报过的船舶。
- 航行中的大船（Class A）每 2–10 秒播报一次，60 秒通常足以覆盖；锚泊船/小船播报间隔更长，**窗口越长覆盖越全**。
- 若海峡边界框窗口内 **0 帧**，会自动回退到「波斯湾—阿曼湾」大区（`HORMUZ_FALLBACK_BBOX`）再探测一次，用于区分"海峡局部无数据"与"aisstream 该海域整体无岸基覆盖"。卡片会标注实际数据范围与收到的报文帧数。
- ⚠️ aisstream 为**众包岸基接收机**网络，部分海域覆盖可能有限。若长期为 0 帧，需考虑改用商用 AIS 数据源（MarineTraffic / VesselFinder 等）。

#### 采样窗口最大能设多大？
aisstream 的流可以**一直挂着**，协议上没有时长上限（唯一硬约束是连接后须在 **3 秒内**发送订阅）。实际上限来自运行环境：
- 跑在 GitHub Actions 上，**单个作业最长 6 小时**——这是硬上限，但绝不该跑这么久。
- 采样窗口应**远小于报告间隔**（如每 30 分钟一次，则窗口控制在几分钟内）。
- 经验值：常规运行 `60`s 足够；**排查 0 数据时建议临时调到 `180`~`300`**。

### 过去 24h 趋势（方案 B：自累积）
aisstream 无历史接口，故采用"**每次报告把当次快照追加存档**"的方式攒出时间序列：
- 快照写入仓库根目录的 `hormuz_history.json`，由工作流在每次运行后**自动提交回仓库**（需要 `contents: write` 权限，已在 `report.yml` 配好）。
- 报告卡片会展示"📅 24h 趋势"：在区船舶数较上次 / 较最早的变化、区间极值、当前油轮数。
- 保留窗口由 `HORMUZ_HISTORY_HOURS`（默认 24）控制。
- 注意：这是**稀疏采样趋势**（每次报告一个 60s 快照点），用于看通航量随时间的升降，**不等于**"24h 内驶过的所有船只清单"。

### 启用方式
1. 在 [aisstream.io/apikeys](https://aisstream.io/apikeys) 申请 API Key；
2. Settings→Secrets and variables→Actions→新增 `AISSTREAM_API_KEY`（填入你的 Key）。
   **未配置时该模块自动跳过，不影响 Polymarket 主报告。**

### 可选配置
- `HORMUZ_WINDOW_SEC`（Secret，单次采样秒数，默认 60；排查无数据可设 180~300）。
- `HORMUZ_HISTORY_HOURS`（Secret，趋势保留小时数，默认 24）。
- 监测边界框 `HORMUZ_BBOX` 在 `config.py` 中定义，默认 `[[25.5, 55.5], [27.0, 57.3]]`
  （格式 `[[南纬, 西经], [北纬, 东经]]`，覆盖海峡主航道与进出港通道）。

### 本地调试 / 覆盖诊断
```bash
# 分别探测海峡与大区两个边界框，打印帧数/船舶数/服务端错误，定位"0 数据"成因
AISSTREAM_API_KEY=你的key python hormuz.py 180   # 参数为采样窗口秒数，默认 60
```
