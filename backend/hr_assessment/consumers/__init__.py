"""HR12 下游集成边界。

正式结果通过共享事务 Outbox 发布；消费成功只能由目标业务域在完成自己的
幂等处理后写入 ``HrResultApplicationLedger``，本模块不伪造 ACK。
"""

from __future__ import annotations

OUTBOX_EVENT_RESULT_FINALIZED = "hr.assessment.assessment_result.finalized"
OUTBOX_EVENT_RESULT_CORRECTED = "hr.assessment.assessment_result.corrected"
OUTBOX_EVENT_RESULT_REVOKED = "hr.assessment.assessment_result.revoked"
