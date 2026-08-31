"""
hr10_development/providers/stub_providers.py

未对接 Provider 的桩实现。

HR15/Academic/Research — 均返回 NOT_APPLICABLE / UNAVAILABLE。
对接后替换为真实实现。
"""

from hr10_development.providers.base import (
    ProviderResult, ProviderStatus,
    FinanceBudgetProvider, AcademicProvider, ResearchProvider,
    AgreementProvider, DocumentProvider, NotificationProvider,
    AssessmentFactsConsumer,
    ExternalTeacherProvider,
)


class StubFinanceProvider(FinanceBudgetProvider):
    def get_budget_status(self, budget_ref: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data={"status": "UNKNOWN"})
    def get_payment_projection(self, expense_ref: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data={"status": "UNKNOWN"})


class StubAcademicProvider(AcademicProvider):
    def get_teaching_schedule(self, staff_master_id: str, tenant_id: int, period_start, period_end) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data=[], error_message="教务系统未对接")
    def verify_teaching_transformation(self, output_id: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data={"status": "PENDING_EXTERNAL_LINK"})


class StubResearchProvider(ResearchProvider):
    def verify_research_output(self, output_ref: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data={"status": "PENDING_EXTERNAL_LINK"})


class StubAgreementProvider(AgreementProvider):
    def get_agreement(self, agreement_id: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None)
    def create_practice_agreement(self, tenant_id: int, title: str, agreement_type: str, parties_json: dict) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="HR07 Agreement 服务未完全施工")


class StubDocumentProvider(DocumentProvider):
    def upload_evidence(self, tenant_id: int, file_data: bytes, file_name: str, content_type: str) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="文件上传需集成 horilla_documents")
    def generate_download_ticket(self, document_id: str, tenant_id: int, max_uses: int = 1) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None)


class StubNotificationProvider(NotificationProvider):
    def notify(self, tenant_id: int, recipient_ids: list[int], template_code: str, context: dict) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data={"queued": len(recipient_ids)})


class StubAssessmentFactsConsumer(AssessmentFactsConsumer):
    """HR12 考核发展事实引用 Provider 桩。"""
    def get_verified_facts(self, staff_master_id: str, tenant_id: int, as_of=None) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data=[], error_message="HR12 模块未施工")
    def get_plan_completion_indicators(self, staff_master_id: str, tenant_id: int, period_start=None, period_end=None) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, data={}, error_message="HR12 模块未施工")


class StubExternalTeacherProvider(ExternalTeacherProvider):
    """HR08 外聘教师 Provider 桩。"""
    def get_engagement(self, engagement_id: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="HR08 Provider 待集成")
    def check_activity_eligibility(self, engagement_id: str, activity_type: str, tenant_id: int) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="HR08 Provider 待集成")
