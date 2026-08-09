# HR08_EXTERNAL_ACADEMIC_INTEGRATION_MAP（初版 · HR08-S0 输出）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §11/§48/§96/§97/§138.8
> 状态：`DRAFT_V1` —— 教务系统与 IAM 均为外部系统，本文件只定义契约；**不存在真实接口时不得声称已对接**（00 §69）。

## 1. 边界（§11/§138.8）

| 域 | 权威 | HR08 动作 |
|---|---|---|
| 此人可承担什么类型教学服务 | HR08 | `HrExternalAssignment.academic_scope_json`（可承担范围） |
| 此人本学期具体教哪门课/哪个班/多少学时 | **教务系统** | HR08 只存 reference：`source_domain=ACADEMIC, source_object_type=TEACHING_ASSIGNMENT, source_object_id` |
| 课程评价正式结果 | 教务/评教系统 | HR08 展示 `TeachingEvaluationSnapshotRef`（续聘评估读取） |
| 正式课程安排 | 教务系统 | HR08 **禁止做第二套课表** |

## 2. 现状（S0 清点）

- **无任何教务/数字校园集成模块**：grep `academic|教务|teacher_identity|teaching_assignment` 仅在 `hr_staff/models/mapping.py`（HrExternalIdentityMapping 系统映射）与 `hr_time/providers/base.py`（Provider 基类）出现，无业务实现。
- **IAM 现状**：HorillaUser 由 `Employee.save()` 自动创建（username=email/password=phone），无 scoped grant 概念。
- 结论：`ACADEMIC`/`IAM` 集成状态 = `UNAVAILABLE`；HR08-S6 建立 Provider/Event 契约 + 占位实现 + reconciliation，**禁止 mock 冒充成功**。

## 3. 教师身份同步契约（§96/§97）

### HR08 → 教务（写/下发）
```
HrExternalAcademicIdentity
- engagement_id
- external_teacher_no        (HR08 tenant-scoped 编号)
- academic_teacher_id        (教务侧教师号，由教务分配)
- valid_from / valid_to      (绑定 Engagement 期限)
- status                     PENDING / ACTIVE / SUSPENDED / EXPIRED / REVOKED
```
事件：
```
ExternalEngagementActivated → 教务：创建/激活 external teacher identity（asynchronously）
ExternalEngagementEnded     → 教务：停止未来排课权限；保留历史课程事实
```
对账：`HrExternalAcademicIdentity.status` 与教务侧状态定期 reconciliation；漂移 → `Risk=ACADEMIC_IDENTITY_DRIFT`。

### 教务 → HR08（回传）
```
source_domain=ACADEMIC
source_object_type=TEACHING_ASSIGNMENT / COURSE_DELIVERY / TEACHING_EVALUATION
payload：课程/班级/学期/学时/教学状态
```
- HR08 消费回写履职事实（`HrExternalServiceTask` 的 academic reference + `HrExternalWorkloadRecord.source=ACADEMIC_VERIFIED`）；
- 教务不得反向修改 HR08 身份（§138.8）。

## 4. IAM 同步契约（§94/§98/§99）

```
HrExternalAccessGrant          # HR08 权威授权意图
HrExternalProvisioningRequest  # 下发/回收异步任务
- target_system: IAM / ACADEMIC / LIBRARY / CAMPUS_CARD / DOOR_ACCESS / VPN / OA / RESEARCH
- operation: GRANT / REVOKE
- status: PENDING / SUCCESS / FAILED_RETRYABLE / FAILED
```
- 一个 Person 多 Engagement → **one IAM identity + 多 scoped grants**；退出 A 只撤销 A 的 scope，不影响 B（§99）。
- `expires_at <= engagement.end_at + allowed_grace`（§67）。
- webhook/reconciliation 幂等（eventId/providerEventId 去重，00 §16）。

## 5. 任务事实来源映射

| source_domain | 事实类型 | 是否 HR08 权威 | 处理 |
|---|---|---|---|
| ACADEMIC | TEACHING_ASSIGNMENT / COURSE_DELIVERY / TEACHING_EVALUATION | 否（教务权威） | reference + 回写履职事实 |
| HR08 | 非课程服务任务（专业建设/实训/竞赛/科研合作等，§49） | 是 | `HrExternalServiceTask` 直接权威 |
| LEGACY_IMPORT | 历史外聘任务 | 迁移期 | staging + 验证，不自动 VERIFIED |
| OTHER | 其他 | 视情况 | 人工核验 |

## 6. 对账清单（§115 DUAL_READ_COMPARE 扩展）
- `HrExternalAcademicIdentity` 与教务教师目录；
- AccessGrant 与 IAM 实际授权；
- 课程任务 reference 与教务排课；
- 工作量（ACADEMIC_VERIFIED）与教务学时；
- 退出后教务仍保留历史课程事实（不删除）。

## 7. 交付阶段
- S2：`HrExternalAccessGrant`/`HrExternalProvisioningRequest`/`HrExternalAcademicIdentity` 模型 + 状态机；
- S6：`integrations/academic.py`、`integrations/iam.py` Provider 契约 + 占位（`UNAVAILABLE`）+ 重试/reconciliation 骨架；
- S7：学术任务 reference 消费回写；
- S8：退出时教务身份停用 + IAM 回收闭环。
