# HR08_RISK_REGISTER（初版 · HR08-S0 输出）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §106-108/§138/§153 + 00 §151 事故等级
> 状态：`DRAFT_V1`

## 1. 风险分级定义（00 §151）
- **P0**：跨租户 / 身份混淆（正式员工 vs 外聘）/ 重复 Person / 协议缺失却激活 / 任务伪事实 / 账号超期 / 权限回收失败 / 工作量伪造。
- **P1**：核心链阻塞、对账失败、数据漂移。
- **P2**：非阻断质量/体验问题。

## 2. 风险登记表

| ID | 风险 | 等级 | 类别 | 缓解措施 | 责任阶段 |
|---|---|---|---|---|---|
| R01 | 外聘被建成普通正式 Employee / 自动建账号（复用 `Employee.save()` 入口） | P0 | 身份混淆 | HR08 不建 Employee；账号走 AccessGrant+IAM provisioning；legacy 入口 authority 后 redirect | S2/S6/S9 |
| R02 | 自建 `ExternalPerson` 第二自然人表 | P0 | 身份根 | 强制复用 HR03 `HrPerson`；profile 通过 person_id FK | S2 |
| R03 | 跨租户泄漏（A 校看 B 校外聘） | P0 | 安全 | 所有权威表显式 tenant_id；服务端 fail-closed（复用 hr_staff.context 模式）；FK 同 tenant 校验 | S1/S2 |
| R04 | 同名/同证件重复 Person 自动合并 | P0 | 数据 | HR03 PersonIdentityService HARD/LIKELY；POSSIBLE_MATCH 人工 review；跨学校不自动关联 | S3 |
| R05 | 荣誉称号 ≠ 实际受聘混为一谈 | P0 | 业务语义 | TitleAppointment 与 Engagement 分离；HONORARY_TITLE 不默认开放任何权限 | S2/S4 |
| R06 | Engagement 无起止时间 / 状态机缺失 | P0 | 业务语义 | start<end 约束；状态机（DRAFT→…→ENDED）；`end_at` 不能直接改长续聘 | S2/S5/S8 |
| R07 | 协议未签开放长期权限（Agreement gate 缺失） | P0 | 合规 | `agreement_requirement` 默认 `REQUIRED_BEFORE_ACTIVATION`；activation 前校验 HR07 Provider | S5 |
| R08 | 到期账号仍可登录 / 账号超期 | P0 | 安全 | AccessGrant.expires_at ≤ engagement.end_at+grace；T-30/T-7/到期/grace 调度 | S2/S6/S8 |
| R09 | 退出权限不回收 / 回收失败静默 | P0 | 安全 | `ExternalEngagementEnding`→ProvisioningRequest(REVOKE)；失败=CRITICAL 风险不反转 Engagement | S8 |
| R10 | 一个 Engagement 退出误杀另一个 | P0 | 安全 | scoped grants 聚合；只撤销退出 engagement 的 scope | S6/S8 |
| R11 | 教学任务只写备注/课程边界越权 | P0 | 业务语义 | 课程事实 reference 教务；非课程服务任务 HR08 权威；`source_object_type/source_object_id` | S7 |
| R12 | 工作量本人自填且无验证 → HR15 直接发钱 | P0 | 结算 | WorkloadRecord.source 四类；本人提交只作补充；学院验证→HR15 settlement basis | S7 |
| R13 | 到期自动续聘 / 直接改 end_date | P0 | 业务语义 | RenewalReview 人工决策 → 新 Engagement；禁止改端自动续 | S8 |
| R14 | `is_active=False` 冒充退出、历史被删 | P0 | 业务语义 | ExitCase 状态机；历史任务/成果/评价/协议保留；账号停用≠删除 | S8 |
| R15 | Legacy Projection 把外聘自动送进正式 Payroll/Leave/Attendance | P0 | 隔离 | worker_kind=EXTERNAL 标记；`regular_employee/benefits_eligible/payroll_regular/attendance_regular=false`；S9 审计下游 | S9 |
| R16 | 教务/IAM 集成 mock 冒充成功 | P0 | 集成 | Provider 状态 OK/PARTIAL/UNAVAILABLE/STALE/ERROR；无真实接口不得声称对接 | S6 |
| R17 | 外聘教师读取正式员工敏感数据 / IDOR | P0 | 安全 | data scope（SELF/ASSIGNED_TASKS/ENGAGEMENT）；sensitive 字段服务端裁剪；文档 ticket | S2/S6/S7 |
| R18 | 敏感数据（身份证/完整手机号）进日志/列表 | P0 | 隐私 | 加密/fingerprint/mask；日志白名单字段（§133） | S2 |
| R19 | 并发：同一 Person 同时聘用 / workload cap 超占 / 双审批 | P1 | 并发 | 版本乐观锁/行锁/条件唯一/exclusion constraint；并发测试矩阵（§121） | S2/S5 |
| R20 | 重复激活 / provisioning webhook 重复 | P1 | 幂等 | Idempotency-Key；eventId 去重；10 次重试一致 | S5/S6 |
| R21 | 资格过期后自动撤销（应作风险/续聘 blocker） | P1 | 业务语义 | `Risk=QUALIFICATION_EXPIRED`/`ETHICS_REVIEW_EXPIRED`；不自动撤 | S7/S8 |
| R22 | 外聘转正式员工直接改 worker_kind | P1 | 业务语义 | `CONVERT_TO_REGULAR_HR_PROCESS` → HR04/05/03 正式链 | S8 |
| R23 | 公开门户/外聘门户客户端传 tenant_id | P1 | 安全 | token/slug 解析学校；禁止裸 tenant_id（00 §134） | S6 |
| R24 | Excel 批量建账号/权限 | P1 | 安全 | Excel 只允许迁移/任务/工作量 staging；账号权限走 provisioning | S3/S7 |
| R25 | 大数据量列表 Python 后过滤 / N+1 | P2 | 性能 | WHERE→COUNT→ORDER→PAGE；p95 指标（§131） | S3/S7 |

## 3. 风险状态与后续
- 全部风险在 S1/S2 施工前保持 OPEN，代码落地后按阶段关闭并附测试证据；
- 新增发现持续登记，不允许删除已登记事实；
- P0/P1 未清零不得进入 S13 封板（`HR08 NOT READY` 需列 blocker）。
