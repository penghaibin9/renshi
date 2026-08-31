"""
hr_qualification/management/commands/hr09_seed.py —— 种子数据初始化。
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "初始化 HR09 种子数据：Credential Catalog + 国家双师基本标准。"

    def handle(self, *args, **options):
        from hr_qualification.constants import (
            CredentialCategory,
            DoubleTeacherDimension,
            HardOrSoft,
            IssuerType,
            JurisdictionLevel,
            RecognitionLevel,
            RulePackVersionStatus,
            RuleType,
        )
        from hr_qualification.models import (
            HrCredentialCatalogItem,
            HrDoubleTeacherEvidenceRequirement,
            HrDoubleTeacherRule,
            HrDoubleTeacherRulePack,
            HrDoubleTeacherRulePackVersion,
        )

        # ---- catalog ----
        catalog_items = [
            {"code": "TQ-HEDU", "category": "TEACHER_QUALIFICATION", "name": "高等学校教师资格",
             "issuer_type": "EDUCATION_AUTHORITY", "validity_policy": {"type": "permanent"}, "requires_document": True},
            {"code": "TQ-SVTE", "category": "TEACHER_QUALIFICATION", "name": "中等职业学校教师资格",
             "issuer_type": "EDUCATION_AUTHORITY", "validity_policy": {"type": "permanent"}, "requires_document": True},
            {"code": "TQ-SVPI", "category": "TEACHER_QUALIFICATION", "name": "中等职业学校实习指导教师资格",
             "issuer_type": "EDUCATION_AUTHORITY", "validity_policy": {"type": "permanent"}, "requires_document": True},
            {"code": "VQ-L1", "category": "VOCATIONAL_QUALIFICATION", "name": "国家职业资格一级（高级技师）",
             "issuer_type": "MOHRSS", "level_schema": {"levels": [
                 {"code": "LEVEL_1", "name": "高级技师", "rank": 5},
                 {"code": "LEVEL_2", "name": "技师", "rank": 4},
                 {"code": "LEVEL_3", "name": "高级工", "rank": 3},
                 {"code": "LEVEL_4", "name": "中级工", "rank": 2},
                 {"code": "LEVEL_5", "name": "初级工", "rank": 1},
             ]}, "validity_policy": {"type": "permanent"}, "requires_document": True},
            {"code": "VQ-L2", "category": "VOCATIONAL_QUALIFICATION", "name": "国家职业资格二级（技师）",
             "issuer_type": "MOHRSS", "level_schema": {"levels": [
                 {"code": "LEVEL_2", "name": "技师", "rank": 4},
                 {"code": "LEVEL_3", "name": "高级工", "rank": 3},
                 {"code": "LEVEL_4", "name": "中级工", "rank": 2},
                 {"code": "LEVEL_5", "name": "初级工", "rank": 1},
             ]}, "validity_policy": {"type": "permanent"}, "requires_document": True},
            {"code": "SL-L1", "category": "VOCATIONAL_SKILL_LEVEL", "name": "职业技能等级一级（高级技师）",
             "issuer_type": "ASSESSMENT_AGENCY", "validity_policy": {"type": "fixed_years", "years": 3}, "requires_document": True},
            {"code": "NT-SEN", "category": "NON_TEACHER_PROFESSIONAL_TITLE", "name": "非教师系列正高级职称",
             "issuer_type": "TITLE_APPROVAL_AUTHORITY", "validity_policy": {"type": "permanent"}, "requires_document": True},
        ]

        catalog_created = 0
        for item in catalog_items:
            _, is_new = HrCredentialCatalogItem.objects.get_or_create(
                tenant_id=None,
                code=item["code"],
                defaults={
                    "category": item["category"],
                    "name": item["name"],
                    "issuer_type": item.get("issuer_type", "OTHER_ISSUER"),
                    "validity_policy": item.get("validity_policy"),
                    "level_schema": item.get("level_schema"),
                    "requires_document": item.get("requires_document", False),
                },
            )
            if is_new:
                catalog_created += 1

        self.stdout.write(f"[Catalog] created/new: {catalog_created}")

        # ---- national baseline ----
        pack, _ = HrDoubleTeacherRulePack.objects.get_or_create(
            tenant_id=None,
            code="NATIONAL-2022",
            defaults={
                "jurisdiction_level": JurisdictionLevel.NATIONAL_BASELINE,
                "jurisdiction_code": "CN",
                "name": "职业教育双师型教师国家基本标准（2022版）",
                "status": "ACTIVE",
            },
        )

        version, v_created = HrDoubleTeacherRulePackVersion.objects.get_or_create(
            rule_pack_id=pack,
            version_no=1,
            defaults={
                "effective_from": "2022-10-25",
                "status": RulePackVersionStatus.ACTIVE,
                "policy_document_ids": [{"code": "教师厅〔2022〕2号", "url": ""}],
            },
        )

        rule_count = 0
        if v_created or not HrDoubleTeacherRule.objects.filter(version_id=version).exists():
            rules_data = [
                ("DOUBLE_TEACHER_JUNIOR", "ETHICS_AND_CONDUCT", "ETHICS-001", "BOOLEAN_FACT", {"value": True}, "HARD", True),
                ("DOUBLE_TEACHER_JUNIOR", "TEACHING_ABILITY", "TEACH-001", "BOOLEAN_FACT", {"value": True}, "HARD", False),
                ("DOUBLE_TEACHER_JUNIOR", "ENTERPRISE_EXPERIENCE", "ENT-001", "BOOLEAN_FACT", {"value": True}, "HARD", False),
                ("DOUBLE_TEACHER_JUNIOR", "PROFESSIONAL_KNOWLEDGE", "JUN-001", "BOOLEAN_FACT", {"value": True}, "HARD", False),
                ("DOUBLE_TEACHER_JUNIOR", "VOCATIONAL_CERTIFICATE_OR_EQUIV", "JUN-002", "ANY_OF", {"options": ["CERT", "EQUIVALENCY"]}, "HARD", False),
                ("DOUBLE_TEACHER_INTERMEDIATE", "ENTERPRISE_EXPERIENCE", "MID-001", "DURATION", {"min_days": 180}, "HARD", False),
                ("DOUBLE_TEACHER_INTERMEDIATE", "INTERMEDIATE_SKILL_OR_EQUIV", "MID-002", "LEVEL_AT_LEAST", {"min_level": "INTERMEDIATE"}, "HARD", False),
                ("DOUBLE_TEACHER_SENIOR", "ENTERPRISE_EXPERIENCE", "SEN-001", "DURATION", {"min_days": 730}, "HARD", False),
                ("DOUBLE_TEACHER_SENIOR", "SENIOR_SKILL_OR_EQUIV", "SEN-002", "LEVEL_AT_LEAST", {"min_level": "SENIOR"}, "HARD", False),
            ]

            for seq, (level, dim, rule_code, rule_type, expected, hardness, manual) in enumerate(rules_data):
                rule = HrDoubleTeacherRule.objects.create(
                    version_id=version,
                    level=level,
                    dimension_code=dim,
                    rule_code=rule_code,
                    rule_type=rule_type,
                    expected_value_json=expected,
                    hard_or_soft=hardness,
                    manual_review_required=manual,
                    source_provider="HR03_EDUCATION",
                    sequence=seq,
                )
                rule_count += 1

                if rule_type in ("BOOLEAN_FACT", "DURATION", "LEVEL_AT_LEAST"):
                    HrDoubleTeacherEvidenceRequirement.objects.create(
                        rule_id=rule,
                        evidence_category="HR09_CREDENTIAL",
                        min_count=1,
                        document_required=True,
                        verification_required=True,
                    )

        self.stdout.write(f"[RulePack] NATIONAL-2022 (new_version={1 if v_created else 0}, rules={rule_count})")
        self.stdout.write(self.style.SUCCESS("HR09 种子数据初始化完成。"))
