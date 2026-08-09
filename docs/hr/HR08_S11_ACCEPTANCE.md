# HR08-S11 生产级验收（文件已交付，待 CI 执行）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §150
> 本文件为 S11 验收矩阵；实际执行需在 CI（PostgreSQL）环境运行（本机 shell 沙箱不可用）。

## 1. 测试套件清单（hr_external/tests/）

| 文件 | 覆盖 | 对应总册 |
|---|---|---|
| `test_s1.py` | constants 无魔法字符串/权限 403/category 模型/API envelope/context fail-closed | §88/§89/§120 |
| `test_s2.py` | 身份根 FK hr_staff.HrPerson/唯一约束/日期约束/重叠阻断/跨租户阻断/状态机/Agreement gate/Provider 契约 | §16-23/§42/§93/00§13 |
| `test_s3.py` | 编号/Selector WHERE→COUNT→ORDER→PAGE/筛选/分页/scope 裁剪/身份匹配/CSV staging/confirm 占位 | §24-26/§82/§110/§120 |
| `test_s4.py` | 专项唯一/贡献状态机/VERIFIED 不可原地改/工作室日期约束 | §27-31/00§20 |
| `test_s5.py` | 审批流/非法转换/合规 BLOCKER/激活事务/协议闸门占位 | §32-43 |
| `test_s6.py` | 授权生命周期/幂等键唯一/聚合回收/撤权失败 Risk/对账漂移 | §94-99/§104/§105 |
| `test_s7.py` | 任务状态机/Task Acceptance/工作量 cap/学院验证/结算只聚合 verified | §44-53 |
| `test_s8.py` | 续聘新聘期不误杀/不续→EXPIRED/转正式→EXITING/退出回收/历史保留 | §58-70 |
| `test_s9.py` | worker_kind=EXTERNAL 标记/regular 全 false/单向投影/SUPERSEDED | §112-113/§6.3 |
| `test_s10_12.py` | 迁移分类/Authority 切换顺序/非法跳级/全部模型 tenant_id + version>=1 约束 | §114/§116-117/00§8/§118 |
| `test_b4_import_execute`（并入 test_s3） | CSV upload→validate→confirm→execute 分批事务真实执行/精确失败行 | §110/HR03§24.3 |
| `test_b5_materials.py` | 材料登记/HMAC 短时效 ticket/篡改/复用/跨租户/过期/REJECTED 全拒/下载审计 | §92/00§34 |
| `test_b6_portal.py` | portal token 明文仅一次/SHA-256 存储/过期/本人视图不含敏感合规 | §90/00§134 |
| `test_b7_dashboard.py` | HR08 工作台指标 Provider（active/expiring90d/industry_experts/scope） | §132/§102 |

## 2. 安全矩阵（§122）

| 项 | 实现 | 状态 |
|---|---|---|
| A 校看不到 B 校 | 全部表 tenant_id + context fail-closed + FK 同 tenant 校验 | ✅ |
| 学院 A 不能看 B 学院 | selector COLLEGE scope 裁剪（§89） | ✅ |
| 本人只看本人 | permissions SELF_VIEW + ExternalScopeType.SELF（S1 定义） | ✅ 待 E2E |
| 任务 assignee 只能读自己任务 | `hr08.task.view` + scope（S7） | ⚠️ 需 portal 集成（S6 后） |
| 外聘不能读正式员工主档 | 身份根只读 HR03 Provider + HR08 无 Employee 敏感数据 | ✅ |
| access expiration | AccessGrant.expires_at ≤ end_at+grace + 对账 | ✅ |
| document IDOR / 导出 scope | S9 后文件安全 ticket 集成 | ⚠️ 待文件集成 |
| identity exact search 权限 | identity-match endpoint 需 `hr08.profile.view`，证件不返回明文 | ✅ |
| ethics/conflict 内部详情 | 服务端裁剪 | ✅ |
| background job tenant | 占位（无 job runner） | ⚠️ 待基建 |
| malformed upload | import_service 校验 CSV UTF-8/字段 | ✅ |
| 跨租户对账隔离 | reconciliation 限定 tenant | ✅ |

## 3. 并发（§121）—— 待 CI 并发测试
1. 同一 Person 同时两个学院相同 Engagement → engagement_service 重叠阻断（SQLite 顺序执行验证；PostgreSQL 并发待 CI）
2. workload cap 同时占满 → cap 校验 + 版本锁
3. 双审批人 final approve → version 乐观锁
4. activation 重复 → LifecycleEvent idempotency_key 唯一
5. provisioning webhook 重复 → idempotency_key 唯一
6. renewal 与 exit 同时 → Engagement 状态机守卫
7. end scheduler 与人工 renew 同时 → 占位（无 scheduler）
8. access revoke 与新 grant 同时 → 事务隔离

## 4. 性能（§131）
- p95 指标定义在总册；实际压测待 CI（10 万人才库分页、dashboard 无 N+1）。
- Selector 已按 WHERE→COUNT→ORDER→PAGE；select_related 消除主要 N+1。

## 5. API Contract（§81-87）
- envelope `apiVersion/schemaVersion/requestId/generatedAt` ✅
- error envelope `{error:{code,message,details,retryable}}` ✅
- 幂等：provisioning/lifecycle idempotency_key tenant 唯一 ✅
- V1 additive-only：常量枚举只在末尾追加 ✅

## 6. E2E 主链（§128）—— 覆盖映射
1 学院提需求（hiring-create）→ 2 建 Person/Profile（person-provider+profile-create）→ 3 行业经历（industry-profile）→ 4 资格/师德/冲突审查（compliance+ethics）→ 5 学院意见（hiring-approve）→ 6 HR 审批 → 7 学校批准（compliance BLOCKER 守卫）→ 8 HR07 签协议（agreement gate 占位）→ 9 Activate（hiring-activate 事务）→ 10 IAM/教务 identity（access-provision/academic 占位）→ 11 分配任务（task-create）→ 12 外聘接受（task-accept）→ 13 教务回传工作量（workload source=ACADEMIC_VERIFIED）→ 14 学院验收（task-verify）→ 15 Settlement Basis（settlement-create）→ 16 到期 Review（renewal-review）→ 17 续聘一年（renewal-decide RENEW→新 Engagement）→ 18 后续不续聘（DO_NOT_RENEW）→ 19 Exit（exit-create）→ 20 权限回收（exit-complete → access revoke）→ 21 历史课程仍可查（历史保留）。

## 7. 目标数据库（00 §26）
- 迁移 0001-0009 已在文件层核对；PostgreSQL 全绿待 CI。
- SQLite 仅轻量单测；btree_gist/exclusion constraint 未用（SQLite 不支持）——用 service 校验 + 行锁替代。
