# Polymarket 市场报告

立即运行一次 Polymarket 市场报告，抓取最新价格数据并发送至企业微信/飞书。

## 使用方式

```
/polymarket-report [slug1,slug2,...]
```

- 不传参数：使用 `config.py` 中配置的默认 `SLUGS`
- 传入参数：临时覆盖 SLUGS，逗号分隔，例如 `/polymarket-report will-trump-win,btc-50k`

## 执行步骤

1. 检查当前工作目录是否为项目根目录（含 `report.py`）
2. 确认 Python 依赖已安装（`requirements.txt`）
3. 根据用户是否传入参数，决定如何运行：

**无参数时：**
```bash
python report.py
```

**有参数时（临时覆盖 SLUGS）：**
```bash
MARKET_SLUGS="<用户传入的slug列表>" python report.py
```

4. 输出运行日志，告知用户报告是否发送成功

## 注意事项

- 需要提前在环境变量或 GitHub Secrets 中配置：`OPENAI_API_KEY`、`FEISHU_WEBHOOK` 或企业微信相关配置
- 报告发送方式取决于 `config.py` 中的 `MPNEWS_ENABLED` 设置
- 如遇错误，检查网络连接和 API 密钥是否有效
