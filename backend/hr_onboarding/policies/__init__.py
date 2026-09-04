"""hr_onboarding.policies —— HR05 业务规则层（状态机/完成定义/人员匹配）。

写操作的持久幂等统一由 services.idempotency_service 提供，不在 policy 层使用缓存。
"""
