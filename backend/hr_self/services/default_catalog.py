"""Default HR17 SELF service catalog for a newly provisioned school.

These rows are experience/navigation configuration only. They deliberately do
not create or mirror HR03-HR16 business facts. A school that already has any
catalog configuration is treated as customized and is left untouched.
"""

from __future__ import annotations

from django.db import transaction

from hr_self.models import SelfServiceCatalogItem


DEFAULT_SELF_SERVICES = (
    {
        "service_code": "MY_STAFF_FILE",
        "name": "查看我的人事档案",
        "source_domain": "HR03",
        "action_key": "VIEW_SELF_STAFF_FILE",
        "route": "/hr/self/files/",
        "sort_order": 10,
        "search_keywords": "档案 主档 基本信息 材料 更正 人事档案",
    },
    {
        "service_code": "MY_RECRUITMENT_PROGRESS",
        "name": "查看招聘录用进度",
        "source_domain": "HR04",
        "action_key": "VIEW_SELF_RECRUITMENT_PROGRESS",
        "route": "/hr/self/progress/",
        "sort_order": 20,
        "search_keywords": "招聘 应聘 录用 offer 进度",
    },
    {
        "service_code": "MY_ONBOARDING_PROGRESS",
        "name": "查看入职办理进度",
        "source_domain": "HR05",
        "action_key": "VIEW_SELF_ONBOARDING_PROGRESS",
        "route": "/hr/self/progress/",
        "sort_order": 30,
        "search_keywords": "入职 报到 材料 任务 试用期 进度",
    },
    {
        "service_code": "MY_CHANGE_PROGRESS",
        "name": "查看人事异动进度",
        "source_domain": "HR06",
        "action_key": "VIEW_SELF_CHANGE_PROGRESS",
        "route": "/hr/self/progress/",
        "sort_order": 40,
        "search_keywords": "异动 调岗 调动 借调 变更 进度",
    },
    {
        "service_code": "MY_CONTRACTS",
        "name": "查看我的聘用合同",
        "source_domain": "HR07",
        "action_key": "VIEW_SELF_CONTRACTS",
        "route": "/hr/self/contracts/",
        "sort_order": 50,
        "search_keywords": "合同 聘用 续签 到期 协议 文件",
    },
    {
        "service_code": "MY_ASSESSMENTS",
        "name": "查看考核进度与结果",
        "source_domain": "HR12",
        "action_key": "VIEW_SELF_ASSESSMENTS",
        "route": "/hr/self/progress/",
        "sort_order": 60,
        "search_keywords": "年度考核 聘期考核 师德 结果 异议",
    },
    {
        "service_code": "MY_TITLE_APPLICATIONS",
        "name": "查看职称申报进度",
        "source_domain": "HR13",
        "action_key": "VIEW_SELF_TITLE_APPLICATIONS",
        "route": "/hr/self/progress/",
        "sort_order": 70,
        "search_keywords": "职称 申报 评审 公示 申诉 进度",
    },
    {
        "service_code": "MY_APPOINTMENTS",
        "name": "查看岗位聘任进度",
        "source_domain": "HR14",
        "action_key": "VIEW_SELF_APPOINTMENTS",
        "route": "/hr/self/progress/",
        "sort_order": 80,
        "search_keywords": "岗位 聘任 聘期 续聘 竞聘 进度",
    },
    {
        "service_code": "MY_PAYSLIPS",
        "name": "查看我的工资结果",
        "source_domain": "HR15",
        "action_key": "VIEW_SELF_PAYSLIPS",
        "route": "/hr/self/payslips/",
        "sort_order": 90,
        "search_keywords": "工资 薪酬 工资条 发放 薪资",
    },
    {
        "service_code": "MY_EXIT_RETIREMENT",
        "name": "查看离退办理进度",
        "source_domain": "HR16",
        "action_key": "VIEW_SELF_EXIT_RETIREMENT",
        "route": "/hr/self/progress/",
        "sort_order": 100,
        "search_keywords": "退休 离校 离职 离退 延迟退休 进度",
    },
)


@transaction.atomic
def ensure_default_catalog_if_empty(tenant_id: int) -> int:
    """Seed an honest read-only/navigation catalog only for an empty tenant.

    Existing school customization, including disabled rows, is never overwritten.
    ``ignore_conflicts`` makes first-login races harmless under the unique tenant/
    service-code constraint.
    """

    if not tenant_id:
        raise ValueError("tenant_id is required")
    if SelfServiceCatalogItem.objects.filter(tenant_id=tenant_id).exists():
        return 0

    rows = [
        SelfServiceCatalogItem(
            tenant_id=tenant_id,
            audience="SELF",
            enabled=True,
            **definition,
        )
        for definition in DEFAULT_SELF_SERVICES
    ]
    SelfServiceCatalogItem.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)
