import json
import io
import os
import textwrap
import pandas as pd
import matplotlib
matplotlib.use("Agg")           # 无头环境，不弹窗
from matplotlib import font_manager, rcParams
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 直接从字体文件读取真实内部名称，避免手写名称与字体元数据不匹配
_WQY_FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_CJK_FONT_NAME = None
if os.path.exists(_WQY_FONT):
    font_manager.fontManager.addfont(_WQY_FONT)
    _CJK_FONT_NAME = font_manager.FontProperties(fname=_WQY_FONT).get_name()

rcParams["font.family"] = "sans-serif"
rcParams["font.sans-serif"] = (
    [_CJK_FONT_NAME] if _CJK_FONT_NAME else []
) + ["Noto Sans CJK SC", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False
rcParams["font.size"] = 10
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL   # 原有配置，保持不动


client = OpenAI(api_key=OPENAI_API_KEY)


# ──────────────────────────────────────────
# 原有函数（保持不变）
# ──────────────────────────────────────────
def translate_to_chinese(texts: list) -> list:
    """
    批量将英文市场问题翻译为中文，逐行一一对应。
    失败或行数不匹配时返回原文列表。
    """
    if not texts:
        return []
    prompt = (
        "请逐行将以下 Polymarket 预测市场问题翻译为简洁自然的中文，"
        "一行对应一行，不加序号和额外说明：\n\n"
        + "\n".join(texts)
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    translated = [
        line.strip()
        for line in resp.choices[0].message.content.strip().split("\n")
        if line.strip()
    ]
    return translated if len(translated) == len(texts) else texts


def translate_sub_options_short(group_question: str, sub_questions: list) -> list:
    """
    将多选项市场的子选项翻译为简短的中文标签。
    以 group_question（已译）为上下文，去掉各选项中与组问题重复的部分，
    只保留关键区分信息（日期、数值、条件等）。
    失败或行数不匹配时返回原文列表。
    """
    if not sub_questions:
        return []
    prompt = (
        f"以下是 Polymarket 预测市场「{group_question}」的多个子选项，"
        "请将每个选项翻译为简短的中文标签（去掉与主题重复的上下文，"
        "只保留关键日期、数值或条件），一行对应一行，不加序号和额外说明：\n\n"
        + "\n".join(sub_questions)
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    translated = [
        line.strip()
        for line in resp.choices[0].message.content.strip().split("\n")
        if line.strip()
    ]
    return translated if len(translated) == len(sub_questions) else sub_questions


def analyze_all_slugs(slug_data: list) -> str:
    """
    对所有 slug 市场的当前价格快照给出整体 AI 解读。
    slug_data: [{"slug": ..., "question": ..., "yes_price": float|None, "is_multi": bool}, ...]
    """
    if not slug_data:
        return "暂无数据。"

    summary_list = [
        {
            "slug":      d["slug"],
            "question":  d["question"],
            "yes_price": d["yes_price"],
            "is_multi":  d["is_multi"],
        }
        for d in slug_data
    ]
    prompt = (
        "你是一个预测市场分析师。以下是多个 Polymarket 市场的当前价格快照，"
        "请用中文给出简洁的整体市场概况（200字以内），"
        "重点关注各市场概率水平和值得关注的动向：\n\n"
        + json.dumps(summary_list, ensure_ascii=False, indent=2)
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def analyze_snapshot(snapshot: dict) -> str:
    """原有快照分析，保持不变"""
    prompt = (
        "你是一个预测市场分析师，请根据以下 Polymarket 市场快照数据，"
        "用中文给出简洁的市场解读（100字以内）：\n"
        + json.dumps(snapshot, ensure_ascii=False, indent=2)
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────
# 新增：高频数据统计摘要
# ──────────────────────────────────────────
def summarize_highfreq(df: pd.DataFrame, mode: str = "1min") -> dict:
    """
    计算高频数据的统计摘要。
    返回 dict，供 analyze_highfreq() 和绘图使用。
    """
    if df.empty:
        return {}

    t_min, t_max = df["datetime"].min(), df["datetime"].max()
    price_now    = df["price"].iloc[-1]
    price_open   = df["price"].iloc[0]
    price_change = price_now - price_open

    # 近1小时均价
    last_1h = df[df["datetime"] >= t_max - pd.Timedelta(hours=1)]
    avg_1h  = last_1h["price"].mean() if not last_1h.empty else None

    # 近6小时均价
    last_6h = df[df["datetime"] >= t_max - pd.Timedelta(hours=6)]
    avg_6h  = last_6h["price"].mean() if not last_6h.empty else None

    return {
        "mode"        : mode,
        "period_start": t_min.strftime("%Y-%m-%d %H:%M UTC"),
        "period_end"  : t_max.strftime("%Y-%m-%d %H:%M UTC"),
        "n_records"   : len(df),
        "price_open"  : round(price_open,  4),
        "price_latest": round(price_now,   4),
        "price_change": round(price_change, 4),
        "price_high"  : round(df["price"].max(), 4),
        "price_low"   : round(df["price"].min(), 4),
        "price_mean"  : round(df["price"].mean(), 4),
        "price_std"   : round(df["price"].std(),  4),
        "avg_1h"      : round(avg_1h, 4) if avg_1h is not None else None,
        "avg_6h"      : round(avg_6h, 4) if avg_6h is not None else None,
    }


# ──────────────────────────────────────────
# 新增：AI 解读高频数据
# ──────────────────────────────────────────
def analyze_highfreq(question: str, summary: dict) -> str:
    """
    调用 OpenAI 对高频统计摘要进行中文解读。
    question : 市场问题文本
    summary  : summarize_highfreq() 的返回值
    """
    if not summary:
        return "暂无数据，无法解读。"

    mode_label = "1分钟粒度（近1天）" if summary["mode"] == "1min" else "日度（近30天）"
    prompt = (
        f"你是一个预测市场分析师。以下是 Polymarket 市场「{question}」的{mode_label}价格统计摘要，"
        "请用中文给出简洁的走势解读（150字以内），重点关注：\n"
        "1. 当前概率水平及近期变化方向\n"
        "2. 价格波动是否异常\n"
        "3. 对事件发生概率的判断\n\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────
# 新增：绘制高频走势图，返回 bytes
# ──────────────────────────────────────────
def _draw_highfreq_axes(ax1, ax2, df: pd.DataFrame, question: str, mode: str):
    """
    在已有的两个 Axes 上绘制高频走势图（上：价格曲线，下：变动柱状）。
    供 plot_highfreq 和 plot_all_highfreq_combined 共用。
    All labels are in English to avoid font/encoding issues.
    """
    import datetime as _dt

    mode_label = "1min · 24h" if mode == "1min" else "Daily · 30d"
    fmt        = "%m-%d %H:%M" if mode == "1min" else "%m-%d"

    # 将 tz-aware datetime 转为 tz-naive，避免 matplotlib 兼容性问题
    if hasattr(df["datetime"].dtype, "tz") and df["datetime"].dt.tz is not None:
        ts = df["datetime"].dt.tz_convert("UTC").dt.tz_localize(None)
    else:
        ts = df["datetime"]

    price_now  = df["price"].iloc[-1]
    price_open = df["price"].iloc[0]
    chg        = price_now - price_open
    chg_color  = "#2ecc71" if chg >= 0 else "#e74c3c"
    chg_sign   = "+" if chg >= 0 else ""

    # ── 上图：价格走势 ──
    ax1.plot(ts, df["price"], color="#4f8ef7", linewidth=1.5, label="YES prob.", zorder=3)
    ax1.fill_between(ts, df["price"], alpha=0.12, color="#4f8ef7")
    y_lo = max(0.0, df["price"].min() - 0.06)
    y_hi = min(1.0, df["price"].max() + 0.06)
    ax1.set_ylim(y_lo, y_hi)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax1.set_ylabel("Prob.", fontsize=9, labelpad=4)

    # 标题：英文问题 + 粒度，自动换行防溢出
    title_text = textwrap.fill(f"{question}  [{mode_label}]", width=72)
    ax1.set_title(title_text, fontsize=9, fontweight="bold", pad=6, loc="left")

    # 右上角：当前价格 + 涨跌幅（纯 ASCII，无需中文字体）
    ax1.annotate(
        f"Now {price_now:.1%}  ({chg_sign}{chg:.1%})",
        xy=(1, 1), xycoords="axes fraction",
        fontsize=9, ha="right", va="top",
        color=chg_color, fontweight="bold",
        xytext=(-4, -4), textcoords="offset points",
    )
    ax1.legend(fontsize=8, loc="upper left", framealpha=0.6)
    ax1.grid(True, which="major", alpha=0.25, linestyle="--")
    ax1.set_facecolor("#f8f9fa")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
    ax1.tick_params(axis="x", rotation=25, labelsize=8)
    ax1.tick_params(axis="y", labelsize=8)
    ax1.spines[["top", "right"]].set_visible(False)

    # ── 下图：价格变动柱状 ──
    diff   = df["price"].diff()
    bar_w  = _dt.timedelta(minutes=1.5) if mode == "1min" else _dt.timedelta(hours=18)
    colors = ["#2ecc71" if (pd.notna(v) and v >= 0) else "#e74c3c" for v in diff]
    ax2.bar(ts, diff, color=colors, width=bar_w, alpha=0.80, zorder=3)
    ax2.axhline(0, color="#888888", linewidth=0.8, zorder=2)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:+.1%}"))
    ax2.set_ylabel("Change", fontsize=9, labelpad=4)
    ax2.set_facecolor("#f8f9fa")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
    ax2.tick_params(axis="x", rotation=25, labelsize=8)
    ax2.tick_params(axis="y", labelsize=8)
    ax2.grid(True, which="major", alpha=0.25, linestyle="--")
    ax2.spines[["top", "right"]].set_visible(False)


def plot_highfreq(df: pd.DataFrame, question: str,
                  mode: str = "1min") -> bytes:
    """
    绘制单张高频价格走势图。
    返回 PNG bytes，供 notifier 直接发送，不写磁盘。
    """
    if df.empty:
        return b""

    fig, axes = plt.subplots(2, 1, figsize=(13, 7),
                              gridspec_kw={"height_ratios": [3, 1], "hspace": 0.45})
    fig.patch.set_facecolor("#ffffff")
    _draw_highfreq_axes(axes[0], axes[1], df, question, mode)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def plot_all_highfreq_combined(entries: list) -> bytes:
    """
    将多个市场、多个粒度的走势图合并为一张从上到下排列的长图。

    entries 格式（与 _collect_all_highfreq_data 返回值一致）：
      [{"question": str, "modes": {"1min": {"df": df, ...}, "1day": {...}}}, ...]

    每个 (question, mode) 组合占两行（价格 + 变动），图表从上到下依次排列。
    返回 PNG bytes；若无任何有效数据则返回 b""。
    """
    # 收集有效的 (question, mode, df) 三元组
    panels = []
    for entry in entries:
        for mode in ["1min", "1day"]:
            data = entry["modes"].get(mode)
            if data and data.get("df") is not None and not data["df"].empty:
                panels.append((entry["question"], mode, data["df"]))

    if not panels:
        return b""

    n = len(panels)
    # 每个 panel 占 2 行（上：价格曲线 3份，下：涨跌柱 1份）
    height_ratios = []
    for _ in panels:
        height_ratios += [3, 1]

    fig, all_axes = plt.subplots(
        n * 2, 1,
        figsize=(13, 5.2 * n),
        gridspec_kw={"height_ratios": height_ratios, "hspace": 0.55},
    )
    # 确保 all_axes 始终是列表
    all_axes = [all_axes] if n * 2 == 1 else list(all_axes)

    fig.patch.set_facecolor("#ffffff")

    for i, (question, mode, df) in enumerate(panels):
        ax1 = all_axes[i * 2]
        ax2 = all_axes[i * 2 + 1]
        _draw_highfreq_axes(ax1, ax2, df, question, mode)

    fig.tight_layout()
    buf = io.BytesIO()
    # 面板越多 DPI 越低，确保合并长图不超过企微 2 MB 图片限制
    dpi = max(72, 120 - n * 4)
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="#ffffff")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


