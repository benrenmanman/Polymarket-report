import requests
import base64
import hashlib
from config import WECOM_WEBHOOK_URL


def send_text(content: str):
    """发送纯文本消息（保留向后兼容）"""
    payload = {
        "msgtype": "text",
        "text": {"content": content}
    }
    resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code != 200 or resp.json().get("errcode", 0) != 0:
        print(f"[notifier] 文本消息发送失败: {resp.text}")


def upload_image(image_bytes: bytes) -> str:
    """
    上传图片到企微，返回 media_id
    文档：https://developer.work.weixin.qq.com/document/path/99110#文件上传接口
    """
    # 从 webhook URL 提取 key
    key = WECOM_WEBHOOK_URL.split("key=")[-1]
    upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"
    
    # 生成文件名（使用内容哈希避免重复）
    file_hash = hashlib.md5(image_bytes).hexdigest()[:8]
    filename = f"chart_{file_hash}.png"
    
    files = {"media": (filename, image_bytes, "image/png")}
    resp = requests.post(upload_url, files=files, timeout=30)
    
    if resp.status_code != 200:
        raise Exception(f"图片上传失败: {resp.status_code}")
    
    result = resp.json()
    if result.get("errcode", 0) != 0:
        raise Exception(f"图片上传失败: {result}")
    
    return result["media_id"]


def send_template_card_report(
    title: str,
    summary: str,
    sections: list[dict],
    chart_media_ids: list[str] = None
):
    """
    发送图文展示模板卡片
    
    参数：
    - title: 卡片标题
    - summary: 概览文本
    - sections: 内容区域列表，每个元素为 {"title": "xxx", "content": "xxx"}
    - chart_media_ids: 图表的 media_id 列表（可选）
    """
    # 构建水平内容列表
    horizontal_contents = []
    for section in sections:
        horizontal_contents.append({
            "keyname": section.get("title", ""),
            "value": section.get("content", "")
        })
    
    # 构建图片列表
    image_list = []
    if chart_media_ids:
        for media_id in chart_media_ids:
            image_list.append({"media_id": media_id})
    
    payload = {
        "msgtype": "template_card",
        "template_card": {
            "card_type": "news_notice",
            "source": {
                "icon_url": "https://wework.qpic.cn/wwpic/252813_jOfDHtcISzuodLa_1629280209/0",
                "desc": "Polymarket 监控",
                "desc_color": 0
            },
            "main_title": {
                "title": title,
                "desc": summary
            },
            "horizontal_content_list": horizontal_contents[:6],  # 最多6个
            "card_action": {
                "type": 1,
                "url": "https://polymarket.com"
            }
        }
    }
    
    # 添加图片（如果有）
    if image_list:
        payload["template_card"]["image_text_area"] = {
            "type": 1,
            "image_list": image_list[:3]  # 最多3张图
        }
    
    resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code != 200 or resp.json().get("errcode", 0) != 0:
        print(f"[notifier] 模板卡片发送失败: {resp.text}")
    else:
        print(f"[notifier] ✓ 模板卡片已发送: {title}")


def send_markdown_report(title: str, content: str):
    """
    发送 Markdown 格式报告
    适合纯文本内容（不含图片）
    """
    full_content = f"# {title}\n\n{content}"
    
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": full_content
        }
    }
    
    resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code != 200 or resp.json().get("errcode", 0) != 0:
        print(f"[notifier] Markdown 消息发送失败: {resp.text}")
    else:
        print(f"[notifier] ✓ Markdown 已发送: {title}")


# ── 向后兼容的函数 ──
def send_html(content: str):
    """兼容旧代码：将 HTML/Markdown 转为文本发送"""
    send_text(content)


def send_image(image_bytes: bytes, filename: str = "chart.png"):
    """兼容旧代码：单独发送图片"""
    try:
        media_id = upload_image(image_bytes)
        payload = {
            "msgtype": "image",
            "image": {"media_id": media_id}
        }
        resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code != 200 or resp.json().get("errcode", 0) != 0:
            print(f"[notifier] 图片消息发送失败: {resp.text}")
    except Exception as e:
        print(f"[notifier] 图片发送失败: {e}")


def send_highfreq_report(question: str, analysis: str, chart_bytes: bytes):
    """兼容旧代码：发送高频报告"""
    send_text(f"📊 {question}\n\n{analysis}")
    send_image(chart_bytes)
