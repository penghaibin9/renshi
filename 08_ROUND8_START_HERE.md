# 跃科高校人事系统：Round8 HR10 Excel 真闭环与并发租约收口入口（2026-09-16）

本轮唯一基线：`Yueke_University_HR_Round7_20260915.zip`  
基线 SHA256：`647fee0ecd94be1b59c79459d72cac9363e2c2f7b140ffcedb0de6f6d9cd02f7`

施工边界：仅云端沙箱源码副本；**未连接 GitHub、未连接生产服务器、未连接生产数据库**。

## 1. 本轮只解决什么

Round8 不扩菜单，专门封闭 HR10 Excel 导入的两个上线级缺陷：

1. **重复 worker 消费**：旧逻辑把 Job 改成 `PARSE` 后提交事务、释放行锁，再解析文件；第二个 worker 可以随后拿到同一 Job 再解析。
2. **确认导入假成功**：旧 `confirm_import()` 只把 Job 从 `PREVIEW` 改成 `SUCCESS`，并没有把 staging 行真正写入培养计划、培训项目、企业实践项目 authority 表。

本轮目标状态机：

```text
PENDING
  ↓ lease claim
PARSE / VALIDATION
  ↓
PREVIEW
  ↓ explicit confirm + execution lease claim
CONFIRMING
  ↓
EXECUTING
  ├─ all authority rows + row receipts + audit commit → SUCCESS
  └─ any row/write/audit failure → transaction rollback → FAILED
```

## 2. 并发语义

- Job 持久保存 `claim_token`、`lease_expires_at`、`heartbeat_at`。
- 活跃租约未过期时，重复 worker 不再执行同一任务。
- worker 崩溃后只有租约超时才允许新 worker 接管。
- 解析期间定期 heartbeat 续租；失去 claim 的旧 worker 结果不得落库。
- `PREVIEW → CONFIRMING → EXECUTING` 同样使用租约，防止页面双击或多 worker 重复确认。

默认 lease 为 300 秒，可用 `HR10_IMPORT_LEASE_SECONDS` 配置，代码限制在 30～3600 秒。

## 3. 真正的确认导入

`confirm_import()` 不再直接写 `SUCCESS`，而是进入 `execute_import_job()`：

- 锁定同 tenant 的 Job；
- 锁定本 Job 的 staging 行；
- 确认 staging 数量、目标模型、执行状态一致；
- 在正式写入前批量二次检查 authority 冲突和同租户引用；
- 写入 `HrDevelopmentPlan` / `HrLearningProgram` / `HrEnterprisePracticeProject`；
- 每行写回 `target_id`、`execution_status`、`executed_at`；
- 每行生成 `ImportRowExecuted` 审计；
- 全部成功后才在**同一个事务**内把 Job 改为 `SUCCESS` 并生成 `ImportConfirmedAndExecuted` 审计。

只要任意一行、审计或数据库写入失败，正式业务写入整体回滚，Job 进入 `FAILED`，结果摘要标记 `rolledBack=true`、`allOrNothing=true`。

## 4. 额外 fail-closed：个人计划教职工主键不一致

本轮复核发现既有模型契约：

- HR03 `HrStaffMaster.id` = UUID；
- HR10 多处 `staff_master_id`（包括 `HrDevelopmentPlan.staff_master_id`）仍为 BigInteger。

因此 `EXCEL_PLAN + INDIVIDUAL` 当前无法安全表达真实 HR03 主键。Round8 **不猜映射、不把旧数字 ID 冒充 HR03 UUID**，而是在预览校验阶段返回：

`staff_master_id: HR03_UUID_CONTRACT_MISMATCH`

学校/学院等非个人计划、培训项目、企业实践项目继续走本轮真实执行链。个人计划的 UUID 迁移应作为独立 schema/数据迁移工程处理。

## 5. 新增可观察性

新增租户隔离、分页的行结果接口：

```text
GET /api/v1/hr/development/imports/{jobId}/rows?page=1&pageSize=100
```

返回 staging 的 rowNumber、targetModel、targetId、verificationStatus、executionStatus、executedAt、errorMessage、parsedData；不返回 claim token 和原始文件内容。

## 6. 验证结果

已实际执行：

- `python -m compileall`：PASS；
- Round2～Round7 纯源码门禁：**155 passed，25 subtests passed**；
- `scripts/check_hr10_import_contract.py`：**20/20 PASS**。

当前云端执行器没有 Django，因此专项 Django TestCase 无法实际运行：

```text
/opt/pyvenv/bin/python: No module named django
```

所以 Round8 当前状态仍是 **SOURCE_CODE_HOTFIX_CANDIDATE / NOT_RELEASED**。不能把 AST/纯源码门禁冒充 MySQL/Django 动态回归。

## 7. 下一台 QA 机必须跑

```bash
python manage.py migrate --plan
python manage.py migrate
python manage.py test hr10_development.tests.test_excel_import_pipeline -v 2
```

随后至少真实验证：

1. 同一个上传任务并发投递 2 次，只有一个 worker 执行；
2. worker 在 PARSE 中途被杀，租约过期后可接管；
3. PREVIEW 后确认，正式表确实出现对应记录；
4. 双击确认不重复写；
5. PREVIEW 后人工插入同业务编号，确认失败且整批回滚；
6. 跨 tenant jobId 无法执行/读取行结果；
7. 执行中 kill worker，数据库事务回滚，租约过期后安全接管；
8. 迁移前若历史 staging 同一来源行指向多个 target_id，迁移必须 fail-closed。

详细证据见：`docs/reports/HR10_IMPORT_CLOSURE_REPORT_2026-09-16.md`。
