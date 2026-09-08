"""KYC 报告生成：基于代理人录入的客户字段，用规则模板拼装结构化摘要。
不接入外部核保 / 精算数据源，仅作为陪跑项目内部的盘客参考，实际投保建议仍需代理人与专家团复核。
"""

TIER_NOTE = {
    "A": "重点维护客户，建议纳入本期盘客优先跟进名单。",
    "B": "稳定经营客户，建议按双周节奏保持常规联系。",
    "C": "潜力培育客户，建议优先完善家庭结构与保障现状信息。",
}

INCOME_GAP_HINT = {
    "30万以下": "建议优先补齐意外与医疗类基础保障，避免过早切入复杂产品。",
    "30万-50万": "建议围绕家庭主要经济支柱的重疾/寿险保额是否覆盖收入缺口展开沟通。",
    "50万-100万": "建议围绕家庭主要经济支柱的重疾/寿险保额是否覆盖收入缺口展开沟通。",
    "100万-300万": "家庭资产规模较大，建议评估大额保单与资产传承类需求。",
    "300万-500万": "家庭资产规模较大，建议评估大额保单与资产传承类需求。",
    "500万以上": "家庭资产规模较大，建议评估大额保单与资产传承类需求。",
    "": "收入区间信息尚未录入，建议下次沟通时补充。",
}

FAMILY_HINT = {
    "已婚有子女": "关注子女教育金与家庭主险的保额是否充足。",
    "已婚无子女": "关注双方主险保额与养老规划的启动时机。",
    "单身": "关注意外/医疗基础保障，及早规划养老与长期储蓄型产品。",
    "": "家庭结构信息尚未录入，建议下次沟通时补充。",
}


def generate_kyc_text(client):
    """client: sqlite3.Row，需包含 name, tier, age_range, family_status, income_range, existing_policies, risk_notes"""
    lines = []
    lines.append(f"客户编码：{client['name']}（{client['tier']} 类 · {client['source']}）")
    lines.append("")
    lines.append(f"分层建议：{TIER_NOTE.get(client['tier'], '')}")

    age = client["age_range"] or "未录入"
    lines.append(f"年龄区间：{age}")

    family = client["family_status"] or ""
    lines.append(f"家庭结构：{family or '未录入'}　{FAMILY_HINT.get(family, '')}")

    income = client["income_range"] or ""
    lines.append(f"收入/资产区间：{income or '未录入'}　{INCOME_GAP_HINT.get(income, '')}")

    existing = client["existing_policies"] or "未录入"
    lines.append(f"已有保障：{existing}")

    if client["risk_notes"]:
        lines.append(f"风险与关注点：{client['risk_notes']}")

    lines.append("")
    lines.append("说明：本报告由系统按录入字段规则生成，供盘客与保单架构设计参考，不构成核保结论，具体方案请结合专家团意见确认。")
    return "\n".join(lines)
