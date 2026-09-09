"""调用 MiniMax 大模型，把系统里的结构化统计数字转写成成长报告 / 结业报告草稿文字。

设计上的硬约束：这里只接受已经算好的数字（分层分布、出勤率、提交完成度等），
不传任何客户原始信息、经营动态或教练反馈的自由文本原文——避免为了让报告"写得
更有洞察力"而把之前费力脱敏掉的内容又通过这个通道发给外部模型。
"""
import json
import os

import requests

MINIMAX_API_BASE = os.environ.get("MINIMAX_API_BASE", "https://api.minimaxi.com")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01")
MINIMAX_TIMEOUT = 30


class AIReportError(Exception):
    """AI 报告生成失败时抛出；message 是可以直接展示给项目经理的中文提示。"""


def _chat(messages):
    if not MINIMAX_API_KEY:
        raise AIReportError("未配置 MINIMAX_API_KEY，请先在系统环境变量中设置后再试。")

    url = f"{MINIMAX_API_BASE}/v1/text/chatcompletion_v2"
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": MINIMAX_MODEL, "messages": messages}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=MINIMAX_TIMEOUT)
    except requests.exceptions.Timeout:
        raise AIReportError("调用 MiniMax 接口超时，请稍后重试。")
    except requests.exceptions.RequestException as e:
        raise AIReportError(f"调用 MiniMax 接口失败：{e}")

    if resp.status_code != 200:
        raise AIReportError(f"MiniMax 接口返回异常状态码 {resp.status_code}：{resp.text[:300]}")

    try:
        data = resp.json()
    except ValueError:
        raise AIReportError(f"MiniMax 接口返回内容不是合法 JSON：{resp.text[:300]}")

    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code", 0) != 0:
        raise AIReportError(f"MiniMax 接口返回错误：{base_resp.get('status_msg', '未知错误')}")

    choices = data.get("choices") or []
    if not choices:
        raise AIReportError(f"MiniMax 接口未返回任何内容：{json.dumps(data, ensure_ascii=False)[:300]}")

    message = choices[0].get("message") or {}
    content = message.get("content") or choices[0].get("text")
    if not content or not str(content).strip():
        raise AIReportError(f"MiniMax 接口返回内容为空：{json.dumps(data, ensure_ascii=False)[:300]}")
    return str(content).strip()


def build_growth_prompt(agent_name, metrics):
    lines = [
        f"你是保险代理人陪跑训练营的项目教练助理，请根据以下结构化数据，为学员「{agent_name}」"
        f"撰写一段 150-250 字的成长评语草稿，用于成长报告。",
        "要求：只依据下面给出的数字撰写，不要编造任何未提供的具体案例、客户信息或对话细节；"
        "语气专业、客观，兼顾肯定与建设性建议；不要用编号列表，写成连贯的一到两段话。",
        "",
        "数据如下：",
        f"- 客户分层：A 类 {metrics['tier_a']} 人，B 类 {metrics['tier_b']} 人，C 类 {metrics['tier_c']} 人",
        f"- 已完成 KYC 分析的客户数：{metrics['kyc_count']}",
        f"- 经营动态提交完成度：{metrics['econ_submitted']}/{metrics['econ_total']} 期",
        f"- 教练反馈覆盖：{metrics['feedback_count']}/{metrics['econ_submitted']} 次已获得反馈",
        f"- 集中辅导会出勤：{metrics['central_present']}/{metrics['central_total']}",
        f"- 盘客辅导出勤：{metrics['panke_present']}/{metrics['panke_total']}",
        f"- 沙龙 1v1 出勤：{metrics['salon_present']}/{metrics['salon_total']}",
    ]
    return [{"role": "user", "content": "\n".join(lines)}]


def build_final_report_prompt(summary):
    lines = [
        "你是保险代理人陪跑训练营的项目负责人助理，请根据以下全体学员的汇总数据，"
        "撰写一份 300-500 字的训练营结业报告草稿，供项目经理审阅后提交给保司。",
        "要求：只依据下面给出的数字撰写，不要编造具体学员对应的案例或客户细节；"
        "风格正式、总结性，包含总体完成情况、亮点与后续建议；按自然段落组织，不要用编号列表。",
        "",
        "汇总数据如下：",
        f"- 学员总数：{summary['agent_count']}",
        f"- 人均客户分层：A 类 {summary['avg_tier_a']:.1f} 人，B 类 {summary['avg_tier_b']:.1f} 人，"
        f"C 类 {summary['avg_tier_c']:.1f} 人",
        f"- 平均经营动态提交完成率：{summary['avg_econ_rate']:.0%}",
        f"- 平均教练反馈覆盖率：{summary['avg_feedback_rate']:.0%}",
        f"- 平均集中辅导会出勤率：{summary['avg_central_rate']:.0%}",
        f"- 平均盘客辅导出勤率：{summary['avg_panke_rate']:.0%}",
        f"- 平均沙龙 1v1 出勤率：{summary['avg_salon_rate']:.0%}",
        f"- 出勤率最高的学员：{summary['top_attendance_name']}（{summary['top_attendance_rate']:.0%}）",
    ]
    return [{"role": "user", "content": "\n".join(lines)}]


def generate_growth_narrative(agent_name, metrics):
    return _chat(build_growth_prompt(agent_name, metrics))


def generate_final_report_narrative(summary):
    return _chat(build_final_report_prompt(summary))
