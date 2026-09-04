"""
hr_recruitment/policies —— HR04 领域规则（状态机/容量）。

公开报名、Offer 与 HR05 handoff 的幂等均由各 Authority 模型数据库唯一约束和
对应服务实现，不保留进程缓存式 policy。
"""
