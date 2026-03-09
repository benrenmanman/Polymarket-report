from datetime import datetime, timezone, timedelta
from report import run_report, run_all_highfreq_reports   # 新增 run_all_highfreq_reports

# ──────────────────────────────────────────
# 配置：需要监控的市场 slug 列表
# ──────────────────────────────────────────
SLUGS = [
    "will-trump-be-president-on-july-4-2025",
    "us-x-iran-ceasefire-by",
    # 在此继续添加更多市场...
]

# ──────────────────────────────────────────
# 原有逻辑（保持不变）
# ──────────────────────────────────────────
def run_existing_jobs():
    for slug in SLUGS:
        run_report(slug)

# ──────────────────────────────────────────
# 新增：高频数据报告
# ──────────────────────────────────────────
def run_highfreq_jobs():
    run_all_highfreq_reports(SLUGS)

# ──────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────
if __name__ == "__main__":
    print(f"[fetch_job] 开始执行 @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # 原有任务
    run_existing_jobs()

    # 新增高频任务
    run_highfreq_jobs()

    print("[fetch_job] 全部完成")
