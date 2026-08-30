"""
hr10_development/legacy/projection.py

Legacy Projection 服务（S10/S12）。

Authority 切换后：只允许 New Authority → Legacy Projection 单向投影。
旧页面/Employee.profile/qualification 字段只读投影。
"""


class LegacyProjectionService:
    """旧系统投影服务。将 HR10 authority 投影到旧 Employee 模型字段。"""

    @staticmethod
    def project_training_summary(staff_master_id: int, tenant_id: int) -> dict:
        """
        投影培训摘要到旧 Employee 字段。

        Returns:
            {"totalTrainingHours": 286, "latestTraining": "2026年新教师培训", "verifiedCredits": 12}
        """
        from hr10_development.models.development_fact import HrDevelopmentFact
        from hr10_development.constants import FactType

        facts = HrDevelopmentFact.objects.effective().filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            fact_type=FactType.TRAINING_COMPLETION,
        ).order_by("-valid_from")

        total_hours = sum(
            float(f.verified_hours or 0) for f in facts[:200]
        )
        total_credits = sum(
            float(f.verified_credits or 0) for f in facts[:200]
        )
        latest = facts.first()

        return {
            "totalTrainingHours": int(total_hours),
            "totalVerifiedCredits": int(total_credits),
            "latestTraining": latest.source_case_type if latest else "",
            "latestDate": str(latest.valid_from) if latest and latest.valid_from else "",
        }

    @staticmethod
    def project_practice_summary(staff_master_id: int, tenant_id: int) -> dict:
        """投影企业实践摘要。"""
        from hr10_development.models.development_fact import HrDevelopmentFact
        from hr10_development.constants import FactType

        facts = HrDevelopmentFact.objects.effective().filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            fact_type=FactType.ENTERPRISE_PRACTICE,
        ).order_by("-valid_from")

        total_days = sum(f.verified_days or 0 for f in facts[:200])

        return {
            "totalPracticeDays": total_days,
            "latestPractice": str(facts.first().valid_from) if facts.first() else "",
        }

    @staticmethod
    def project_to_employee_qualification_field(staff_master_id: int, tenant_id: int) -> str:
        """
        投影到旧 Employee.qualification 字段（只读标签）。

        Authority 切换后：旧 qualification 字段 = 投影，不再直接编辑。
        """
        training = LegacyProjectionService.project_training_summary(staff_master_id, tenant_id)
        practice = LegacyProjectionService.project_practice_summary(staff_master_id, tenant_id)

        parts = []
        if training["totalTrainingHours"]:
            parts.append(f"已核验培训 {training['totalTrainingHours']} 学时")
        if practice["totalPracticeDays"]:
            parts.append(f"企业实践 {practice['totalPracticeDays']} 天")
        return "；".join(parts) if parts else ""
