# 跃科高校人事系统：Round9 HR10 教职工 UUID 权威身份收口入口（2026-09-16）

本轮唯一基线：`Yueke_University_HR_Round8_20260916.zip`  
基线 SHA256：`720912d3598f5cc7ed21ebe083a814191aed8f7c1866f9aebd852bfab87850a0`

施工边界：仅云端沙箱源码副本；**未连接 GitHub、未连接生产服务器、未连接生产数据库**。

## 1. 本轮解决的根问题

Round8 在 HR10 Excel 真闭环收口时确认了一个跨模块根契约冲突：

- HR03 权威人员主键 `HrStaffMaster.id` 已是 UUID；
- HR10 多张核心业务表历史上仍把旧 `Employee.id / legacy_employee_id` BigInteger 当作 `staff_master_id`；
- HR11 排班/请假仍使用旧数字人员键；
- HR10 已封存 `HrDevelopmentFact` 又是 append-only + 内容哈希 + MySQL 不可变触发器，不能粗暴批量重写历史事实。

如果只把字段类型从 BigInteger 改成 UUID，会同时破坏历史哈希、HR11 联动、旧深链和历史导入；如果继续使用 BigInteger，则个人计划、培训报名、企业实践、成果、HR09 证据会长期偏离 HR03 Authority。

Round9 采用**Canonical UUID + legacy compatibility bridge**：

```text
HR03 HrStaffMaster.id (UUID)        ← HR10 新权威人员键
          │
          ├─ unique legacy_employee_id → 仅兼容旧 HR10 / HR11
          │
          └─ missing / duplicate legacy mapping → fail-closed
```

## 2. 数据模型

以下 10 个 HR10 staff-bearing 模型新增 `staff_master_uuid`：

- HrDevelopmentPlan
- HrTrainingRequest
- HrLearningEnrollment
- HrDevelopmentNeed
- HrFurtherStudyCase
- HrEnterprisePracticeAssignment
- HrDevelopmentOutput
- HrDevelopmentFact
- HrDevelopmentMetricLedger
- HrDevelopmentRiskCase

新核心写入统一写 UUID；存在安全、唯一的旧 Employee 映射时同时保留旧数字 ID，仅用于过渡兼容。

原来必填 BigInteger 的 7 张表为了允许“HR03 有 UUID、没有旧 Employee ID”的新教师改为 nullable，但 Round9 同时增加 DB `CheckConstraint`，要求 `staff_master_uuid` / `staff_master_id` 至少一个存在，避免兼容改造削弱原有非空保护。

## 3. MySQL 迁移拆成三段

考虑 MySQL DDL 不具备完整事务回滚能力，本轮没有把所有动作塞进一个迁移：

1. `0026_canonical_hr03_staff_uuid.py`：**只做结构**，增加 UUID 字段、放宽旧 BigInteger；不跑数据回填。
2. `0027_backfill_hr10_staff_uuid.py`：**只做数据预检与回填**。先一次性核验 tenant + legacy 映射无缺失、无歧义，再写 mutable 业务表；可修复脏数据后安全重跑。
3. `0028_hr10_staff_identity_guards.py`：**约束与触发器**。数据库约束/index 创建前先 introspection，支持失败后幂等重试；更新发展事实 parent trigger。

0027 **故意不改**已封存 `HrDevelopmentFact`。历史 V1 内容哈希继续按旧 bigint 字段验证；未来更正/撤销若可安全映射，会生成带 UUID 的 V2 successor，而不是修改 parent。

## 4. 历史事实防串人

HR03 的 `legacy_employee_id` 当前没有唯一约束，因此 Round9 不假设它天然安全：

- 数字 ID 解析：同租户 0 条 → NOT_FOUND；大于 1 条 → `STAFF_IDENTITY_AMBIGUOUS`；
- UUID 解析：如果该 UUID 对应的 legacy ID 在同租户被多个 HR03 staff 复用，同样 fail-closed；
- HR09 public evidence：重复 legacy bridge → `SOURCE_IDENTITY_MAPPING_AMBIGUOUS`，绝不把旧事实分配给任意一个教师；
- HR11：只有唯一 legacy 映射才允许落到旧排班/请假表；缺失/歧义均返回 `SOURCE_UNAVAILABLE`，不冒充“无冲突”。

## 5. 核心业务链已切换 UUID

已覆盖：

- 个人发展计划创建；
- 培训申请；
- 报名 / 候补；
- 企业实践派出；
- 发展成果；
- 培训完成 → DevelopmentFact；
- 发展事实更正/撤销 successor；
- 风险案例；
- 发展档案、合规、legacy projection、HR09 evidence；
- HR11 时间冲突边界；
- HR10 工作台教师下拉与发展档案深链；
- Round8 Excel 个人计划：UUID 可直接导入，旧数字 ID 仅经 tenant-scoped HR03 唯一映射后接受。

旧数字发展档案 URL 仍能通过 resolver 兼容；新 UI 输出 UUID。

## 6. 审批自审同步修正

培训申请的 approve / return / reject 全部统一到同一个 self-approval guard：优先比较申请人与审批人的 HR03 UUID；只有兼容场景才退回旧 actor ID 比较。服务层在重新锁行后再次判断，前端/API 的预判断不能替代最终服务层保护。

## 7. 当前已实际执行的门禁

- HR10 144 个 Python 源文件 AST：PASS；
- `scripts/check_hr10_import_contract.py`：**20/20 PASS**；
- `scripts/check_hr10_staff_identity_contract.py`：**53/53 PASS**；
- Round2～Round7 + Round9 纯源码 unittest：**159/159 PASS**；
- Round9 纯身份专项 unittest：5/5 PASS（包含在上面的 159）。

当前云端执行器**没有 Django**。实际执行 `manage.py makemigrations --check --dry-run` 与 HR10 专项 TestCase 均因 `ModuleNotFoundError: No module named 'django'` 终止。因此当前仍是：

**SOURCE_CODE_CANDIDATE / NOT_RELEASED**

不能把 AST/静态门冒充 MySQL migration / Django runtime 验收。

## 8. 下一台有依赖的 QA 环境必须执行

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py migrate --check
python manage.py test \
  hr10_development.tests.test_excel_import_pipeline \
  hr10_development.tests.test_hr11_time_conflict_provider \
  hr10_development.tests.test_public_identity_contract \
  hr10_development.tests.test_development_fact_authority \
  hr10_development.tests.test_further_study_hr03_writeback \
  hr10_development.tests.test_e2e -v 2
```

至少真实验证：

1. 0027 遇到缺失/重复 legacy 映射时必须在回填前 fail-closed；
2. 修好数据后可重跑 0027/0028，不因 MySQL 已提交 DDL 卡死；
3. UUID-only 教师可以创建 HR10 计划/申请/成果；
4. UUID-only 教师需要 HR11 时明确 SOURCE_UNAVAILABLE；
5. 同租户重复 legacy_employee_id 不得把旧事实串到另一个 UUID；
6. 历史 V1 DevelopmentFact hash 仍可验证；
7. V1 fact 正式更正生成 V2 UUID successor，parent 不被修改；
8. 个人计划 Excel UUID / 唯一 legacy 两种输入均真实写入 UUID；
9. 新报名的 canonical unique constraint 与旧数据 unique_together 不发生误冲突；
10. approve / return / reject 均禁止本人审批。

详细证据：`docs/reports/HR10_STAFF_IDENTITY_CLOSURE_REPORT_2026-09-16.md`。
