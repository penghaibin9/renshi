# HR10 Excel 导入并发与真闭环收口报告

日期：2026-09-16  
基线：`Yueke_University_HR_Round7_20260915.zip`  
基线 SHA256：`647fee0ecd94be1b59c79459d72cac9363e2c2f7b140ffcedb0de6f6d9cd02f7`  
本轮结论：**两个已确认的上线级缺陷已做代码级修复；源码门禁通过；Django/MySQL 动态回归因当前执行器缺少 Django 尚未执行。**

## 一、缺陷 A：行锁文档与真实并发语义不一致

### 原问题

旧 worker 的流程本质是：

```text
select_for_update(Job)
→ status=PARSE
→ COMMIT（锁释放）
→ 文件解析
```

因此行锁只保护了“把状态改成 PARSE”的那一小段事务，并没有保护后面的解析工作。第二个 worker 随后仍可锁到该 Job 并再次执行解析。旧注释所称“重复投递无害”并不成立。

### 修复

`HrDevelopmentImportJob` 新增：

- `claim_token`
- `lease_expires_at`
- `heartbeat_at`

解析 worker 必须先 claim：

- `PENDING` 可 claim；
- `PARSE/VALIDATION` 且 lease 未过期 → 重复投递 no-op；
- `PARSE/VALIDATION` 且 lease 已过期 → 允许安全 takeover；
- 解析每 250 行 heartbeat；
- staging 落库和最终状态切换前再次验证 claim token；
- 老 worker 一旦失去 claim，其结果禁止覆盖新 owner。

这把“幂等”从注释改成了持久化状态机事实。

## 二、缺陷 B：confirm_import() 假成功

### 原问题

旧 API 的 `confirm_import()` 只完成：

```text
PREVIEW → SUCCESS
```

并未把 staging 行写入正式 authority 表。因此会出现：

- 页面提示导入成功；
- Job 状态 SUCCESS；
- 但培养计划 / 培训项目 / 企业实践项目中没有数据。

这是典型“状态闭环，业务没闭环”。

### 修复

确认现在进入真实执行服务：

```text
PREVIEW
→ execution lease claim
→ CONFIRMING
→ EXECUTING
→ lock job + lock staging
→ batch authority recheck
→ authority insert
→ row receipt
→ row audit
→ job SUCCESS + job audit
```

正式 authority 目标：

| Excel 类型 | Authority 表模型 |
|---|---|
| EXCEL_PLAN | HrDevelopmentPlan |
| EXCEL_PROGRAM | HrLearningProgram |
| EXCEL_PRACTICE | HrEnterprisePracticeProject |

### 原子性

`authority insert + staging target_id/status + success audit + Job SUCCESS` 放在同一个数据库事务。

因此：

- 任一目标行失败 → 整批正式写入回滚；
- audit 写失败 → 同样回滚；
- 不存在“写了一半还显示 SUCCESS”；
- `FAILED` 在回滚后的独立事务中记录，保留失败行与错误码。

## 三、确认阶段也做租约

页面双击、API 重试、多 worker 同时确认都可能造成重复执行，所以确认阶段也不是单纯判断 `status == PREVIEW`。

新增：

```text
PREVIEW → CONFIRMING → EXECUTING
```

- 活跃执行 lease → 409 `IMPORT_IN_PROGRESS`；
- lease 过期 → 允许 takeover；
- 已 SUCCESS → 返回既有 Job，不再新建 authority 行；
- claim token 不返回前端。

## 四、PREVIEW 与 CONFIRM 之间的竞态

仅在解析时检查业务编号不存在还不够，因为用户预览后、点击确认前，另一个会话可能创建同编号业务记录。

本轮在真正写入前再次批量检查：

- 计划编号；
- 培训项目编码；
- 企业实践项目编号；
- owner_org_id 同 tenant；
- provider_org_id 同 tenant；
- 枚举值。

发现冲突即 `AUTHORITY_CONFLICT_AT_EXECUTION`，整批回滚。

执行前二次校验使用批量查询，避免 10k 行确认产生 N+1 查询风暴；最终数据库唯一约束仍是最后一道并发防线。

## 五、逐行结果与审计

`HrDevelopmentStagingRow` 新增：

- `execution_status`: PENDING / SUCCESS / FAILED / SKIPPED
- `executed_at`
- `(tenant_id, import_job_id, source_object_id)` 唯一约束

成功行写回：

- `target_id`
- `execution_status=SUCCESS`
- `executed_at`
- `ImportRowExecuted` audit

整批成功再写：

- `ImportConfirmedAndExecuted`

失败时写：

- 失败 staging 行 `execution_status=FAILED`
- `ImportExecutionFailed`
- Job result summary：errorCode / failedRow / allOrNothing / rolledBack

## 六、迁移安全

新增 migration：

`backend/hr10_development/migrations/0025_import_claim_lease_and_execution.py`

在加 staging 唯一约束前先检查历史重复行：

- 若重复行最多只关联同一个 target_id → 保留目标已关联行或第一行，删除冗余副本；
- 若同一 `(tenant, job, source row)` 已指向多个不同 target_id → 直接抛出 `HR10_STAGING_DUPLICATE_TARGET_CONFLICT`，阻断迁移；
- 不猜哪个正式目标“才是对的”。

## 七、租户边界

执行服务要求 `job_id + tenant_id` 同时匹配；目标 authority 行统一使用 Job 的 tenant，不接受 Excel 自带 tenant 字段。

owner/provider 引用按同 tenant 校验；行结果 API 同样先校验 Job 属于当前 tenant。

## 八、个人计划 staff key 的既有契约冲突

本轮发现：

- `hr_staff.HrStaffMaster.id` 是 UUID；
- `hr10_development.HrDevelopmentPlan.staff_master_id` 是 BigInteger；
- HR10 其他多个 staff_master_id 也仍是 BigInteger。

这不是本轮 worker 新引入的问题，但会让 `EXCEL_PLAN + INDIVIDUAL` 无法安全引用 HR03 authority。

本轮处理原则：**fail-closed，不制造假外键。**

当个人计划携带数字 `staff_master_id` 时，预览返回：

`staff_master_id: HR03_UUID_CONTRACT_MISMATCH`

不进入 staging，更不会进入正式 authority 表。

后续应单独做“HR10 人员引用 UUID 对齐 + 旧 BigInteger 数据迁移/映射 + 全域回归”，不能在本次导入修复里偷偷改字段类型。

## 九、验证证据

### 已实际通过

1. Python compileall：PASS。
2. Round2～Round7 纯源码门禁：`155 passed, 25 subtests passed`。
3. 新增 `scripts/check_hr10_import_contract.py`：`20/20 PASS`。
4. API 源码不存在旧式 `job.status = "SUCCESS"` 直接确认写法。

静态合同门覆盖：

- lease 字段；
- parse claim；
- execute claim；
- 原子执行；
- 三类真实 authority target；
- 执行前批量冲突复核；
- 逐行结果；
- API 真执行；
- tenant scope；
- rows endpoint；
- fail-closed 历史 staging 去重；
- 个人计划 UUID/BigInteger 冲突阻断；
- 专项回归测试存在。

### 已写入但当前无法实际执行的 Django 回归

`backend/hr10_development/tests/test_excel_import_pipeline.py` 已覆盖：

1. 活跃 parse lease 阻止第二 worker；过期 lease 可 takeover；
2. 个人计划 staff key 契约冲突 fail-closed；
3. confirm 真写 authority + row result + audit；
4. 重复 confirm 不重复写；
5. PREVIEW 后 authority 冲突导致 FAILED + 整批回滚；
6. 跨 tenant confirm 返回 IMPORT_NOT_FOUND；
7. 活跃 execution lease 阻止重复确认。

当前执行器实际尝试 Django test 的结果：

```text
/opt/pyvenv/bin/python: No module named django
```

因此本报告**不声称这些 Django TestCase 已 PASS**。

## 十、上线前 QA 必须完成

必须在安装项目依赖并连接测试 MySQL 的环境执行：

```bash
python manage.py migrate --plan
python manage.py migrate
python manage.py test hr10_development.tests.test_excel_import_pipeline -v 2
```

还要做两个真实并发用例：

- 两 worker 同时消费同一 Job；
- worker 在 EXECUTING 事务中 kill -9，确认未提交 authority 行，等待 lease 后能安全接管。

## 十一、修改文件

核心源码：

- `backend/hr10_development/legacy/import_job.py`
- `backend/hr10_development/legacy/staging.py`
- `backend/hr10_development/services/import_worker.py`
- `backend/hr10_development/api/imports.py`
- `backend/hr10_development/api/urls.py`
- `backend/hr10_development/tests/test_excel_import_pipeline.py`
- `backend/hr10_development/migrations/0025_import_claim_lease_and_execution.py`
- `scripts/check_hr10_import_contract.py`

交付元数据/证据：

- `08_ROUND8_START_HERE.md`
- `docs/reports/HR10_IMPORT_CLOSURE_REPORT_2026-09-16.md`
- `docs/reports/HR10_IMPORT_CONTRACT_STATIC_2026-09-16.json`
- `docs/reports/HR10_DJANGO_TEST_ATTEMPT_2026-09-16.log`

## 十二、当前裁决

**HR10 的“重复 worker”与“confirm 假成功”已做真实代码修复；但由于当前云端没有 Django/MySQL 动态运行时，Round8 仍为 NOT_RELEASED。**

在 QA 动态门通过前，不应把“静态 20/20 + 纯门禁 155”写成“生产已验收”。
