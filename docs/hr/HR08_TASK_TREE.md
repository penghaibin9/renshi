# HR08_TASK_TREE（初版 · HR08-S0 输出）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §139-152
> 状态：`DRAFT_V1`；施工顺序严格按总册 #139（一个阶段一个可验证提交）。

## HR08-S0 基线复审 ✅（本次交付）
- 读取 00/03/07/08 总册 + HR02/HR03/HR04/HR11 已交付代码 + legacy 模块
- 输出 7 份文档：`HR08_LegacyExternalWorkerMapping.md`、`HR08_GAP_MATRIX.md`、`HR08_EXTERNAL_CATEGORY_MATRIX.md`、`HR08_EXTERNAL_ACCESS_POLICY_MATRIX.md`、`HR08_EXTERNAL_ACADEMIC_INTEGRATION_MAP.md`、`HR08_TASK_TREE.md`、`HR08_RISK_REGISTER.md`
- 里程碑闸门：HR03 `HrPerson` tenant-private 身份服务 **已交付**（闸门满足）；HR07 未交付 → `agreement` 用 Provider 契约占位

## HR08-S1 基础 contract（下一步施工）
| 交付物 | 文件 | 验收 |
|---|---|---|
| enums | `hr_external/constants.py` | 与总册 §5/§20/§22/§34/§47/§60/§65/§88/§103 对齐；无魔法字符串 |
| permissions | `hr_external/permissions.py` | 403 fail-closed；scope 校验 |
| External Category | `hr_external/models/category.py` + migration | tenant unique；默认类别 seed |
| API envelope | `hr_external/api/base.py` | apiVersion/schemaVersion/requestId/generatedAt + error envelope |
| 公共 UI | `hr_external/templates/hr_external/components/*` | 状态/类别/期限/风险徽标组件 |

## HR08-S2 Authority Models（闸门已确认 HR03 就绪）
`HrExternalTeacherProfile`、`HrExternalEngagement`、`HrExternalEngagementAssignment`、`HrExternalHiringCase`、`HrExternalEthicsReview`、`HrExternalConflictDeclaration`、`HrExternalAccessGrant`、`HrExternalLifecycleEvent`（+ `HrExternalAuditEvent`/`SensitiveExternalAccessLog`/`HrExternalProvisioningRequest`/`HrExternalAcademicIdentity`）+ migrations/constraints（§118/§119）
- HR07 未交付：`agreement_type_code + agreement_status` Provider 占位解析，不建第二套协议表

## HR08-S3 HR08-01 外聘教师库
Profile list/detail/talent pool/identity match/history/sensitive/import-export（§24-26/§123）

## HR08-S4 HR08-02 产业教授与技能大师
专项 Profile/Contribution/Workspace/evidence/annual review（§27-31/§124）

## HR08-S5 HR08-03 聘用审批
HiringCase/资格/伦理/冲突/审批流/HR07 agreement gate/Activation（§32-43/§125）

## HR08-S6 IAM/教务集成
External directory projection/scoped access/teacher identity/provisioning + reconciliation（§94-99/§96-97）

## HR08-S7 HR08-04 教学与服务任务
TaskPlan/ServiceTask/Academic refs/Evidence/Workload/SettlementBasis（§44-56/§126）

## HR08-S8 HR08-05 续聘与退出
Review/Renewal/Conversion/Exit/Clearance/Access revoke（§58-70/§127）

## HR08-S9 Legacy Projection
Horilla Employee/EmployeeType/WorkInformation projection + worker_kind=EXTERNAL + 下游隔离（§112-113）

## HR08-S10 Legacy Migration + DUAL_READ_COMPARE
分类迁移/重复人人工确认/对账（§116-117/§115）

## HR08-S11 生产级验收
security/concurrency/performance/API contract/E2E/a11y/visual/migration/reconciliation

## HR08-S12 Authority 切换
`LEGACY_EMPLOYEE_TAG_ONLY → DUAL_READ_COMPARE → HR08_AUTHORITY`（§114）

## HR08-S13 最终封板
`HR08 READY FOR ACCEPTANCE`（§152/§154）

## 每个阶段的通用纪律
1. 先列精确文件/模型/API/测试，再改；
2. 每阶段跑专项 + 受影响回归，报告真实通过/失败数量；
3. 不合并 main、不删除 legacy、不降低权限、不用 mock 冒充生产；
4. 跨域写只走 domain service + outbox/event（00 §14/§16）。
