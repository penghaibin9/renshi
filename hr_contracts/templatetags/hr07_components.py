"""
hr_contracts/templatetags/hr07_components.py

21 个可复用 UI 组件（HR07 总册 §99）。
每个组件接受参数，返回纯 HTML（中文标签、状态徽标、配色由 display_labels.py 提供）。
用法：{% load hr07_components %}{% agreement_status_badge obj.lifecycle_status %}
"""

from django import template
from django.utils.html import format_html

from hr_contracts.display_labels import (
    LIFECYCLE_CLASS,
    SEVERITY_CLASS,
    label,
)

register = template.Library()

# ── 徽标类 ────────────────────────────────────────────

@register.simple_tag
def agreement_status_badge(status):
    cls = LIFECYCLE_CLASS.get(status, "oh-badge oh-badge--secondary")
    txt = label("lifecycle_status", status)
    return format_html('<span class="{}">{}</span>', cls, txt)


@register.simple_tag
def agreement_family_badge(family):
    txt = label("agreement_family", family)
    return format_html('<span class="oh-badge oh-badge--info">{}</span>', txt)


@register.simple_tag
def agreement_risk_badge(severity):
    cls = SEVERITY_CLASS.get(severity, "oh-badge oh-badge--secondary")
    txt = label("risk_severity", severity)
    return format_html('<span class="{}">{}</span>', cls, txt)


@register.simple_tag
def contract_review_badge(review_date, lifecycle_status):
    if lifecycle_status == "REVIEW_DUE":
        return format_html('<span class="oh-badge oh-badge--warning">待续聘评审 {}前</span>', str(review_date or ""))
    if lifecycle_status == "RENEWAL_IN_PROGRESS":
        return format_html('<span class="oh-badge oh-badge--warning">续签进行中</span>')
    return format_html('<span class="oh-badge oh-badge--secondary">-</span>')


@register.simple_tag
def signature_status_badge(status):
    txt = label("signature_envelope_status", status)
    cls_map = {
        "DRAFT": "oh-badge oh-badge--secondary",
        "SENT": "oh-badge oh-badge--info",
        "COMPLETED": "oh-badge oh-badge--success",
        "DECLINED": "oh-badge oh-badge--danger",
        "FAILED": "oh-badge oh-badge--danger",
        "EXPIRED": "oh-badge oh-badge--neutral",
    }
    cls = cls_map.get(status, "oh-badge oh-badge--secondary")
    return format_html('<span class="{}">{}</span>', cls, txt)


@register.simple_tag
def template_version_badge(status):
    txt = label("template_status", status)
    cls_map = {
        "DRAFT": "oh-badge oh-badge--secondary",
        "ACTIVE": "oh-badge oh-badge--success",
        "RETIRED": "oh-badge oh-badge--neutral",
    }
    cls = cls_map.get(status, "oh-badge oh-badge--info")
    return format_html('<span class="{}">{}</span>', cls, txt)


# ── 头部/信息卡片 ─────────────────────────────────────

@register.inclusion_tag("hr_contracts/components/agreement_header.html")
def agreement_header(agreement, staff=None):
    return {
        "agreement": agreement,
        "staff": staff or {},
    }


@register.inclusion_tag("hr_contracts/components/agreement_term_table.html")
def agreement_term_table(terms):
    return {"terms": terms}


@register.inclusion_tag("hr_contracts/components/agreement_version_rail.html")
def agreement_version_rail(versions, current_version_id):
    return {"versions": versions, "current_version_id": str(current_version_id or "")}


@register.inclusion_tag("hr_contracts/components/agreement_timeline.html")
def agreement_timeline(events):
    return {"events": events}


@register.inclusion_tag("hr_contracts/components/signature_participants.html")
def signature_participants(participants):
    return {"participants": participants}


@register.inclusion_tag("hr_contracts/components/contract_risk_card.html")
def contract_risk_card(risk):
    return {"risk": risk}


@register.inclusion_tag("hr_contracts/components/contract_date_range.html")
def contract_date_range(agreement):
    return {"agreement": agreement}


@register.inclusion_tag("hr_contracts/components/rule_evaluation_panel.html")
def rule_evaluation_panel(rules):
    return {"rules": rules}


@register.inclusion_tag("hr_contracts/components/renewal_decision_bar.html")
def renewal_decision_bar(review):
    return {"review": review}


@register.inclusion_tag("hr_contracts/components/agreement_event_timeline.html")
def agreement_event_timeline(events):
    return {"events": events}


@register.inclusion_tag("hr_contracts/components/agreement_relationship_map.html")
def agreement_relationship_map(relationships):
    return {"relationships": relationships}
