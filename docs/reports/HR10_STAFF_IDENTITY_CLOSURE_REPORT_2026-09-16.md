# HR10 教职工 UUID Authority 收口报告

日期：2026-09-16  
基线：`Yueke_University_HR_Round8_20260916.zip`  
基线 SHA256：`720912d3598f5cc7ed21ebe083a814191aed8f7c1866f9aebd852bfab87850a0`  
当前裁决：**SOURCE_CODE_CANDIDATE / NOT_RELEASED**

## 1. 缺陷定义

HR03 的人员 Authority 已使用 `HrStaffMaster.id = UUID`，HR10 历史实现却在计划、申请、报名、实践、成果、发展事实等对象中保存旧 `Employee.id` BigInteger。Round8 因此只能对个人计划 Excel fail-closed。继续维持旧实现会产生四类上线风险：

1. UUID 教职工无法形成真实 HR10 人员引用；
2. HR10 与 HR03/HR09 权威证据链主键不一致；
3. 为兼容 HR11 继续传播旧数字主键，使旧实现反向绑架新模块；
4. 直接批量改写已封存 DevelopmentFact 会破坏历史 hash/append-only 审计。

## 2. 最终设计

Canonical key 固定为 HR03 UUID。旧 `legacy_employee_id` 仅作为显式兼容桥，且必须 tenant-scoped、唯一、可核验。

新增 `identity.py` 统一处理：

- UUID-first resolution；
- 数字 legacy resolution；
- tenant isolation；
- missing / invalid / ambiguous 明确错误；
- canonical + untouched historic legacy 双读 Q；
- lineage identity comparison。

HR10 不新增第二个人员主档，也不生成自己的人员 ID。

## 3. Schema 与数据迁移

10 个 HR10 模型增加 `staff_master_uuid`。原来要求 staff BigInteger 非空的 7 张表改为兼容可空，同时新增 DB check，保证 UUID / legacy 至少一个存在。

MySQL 迁移拆为：

- 0026 schema-only；
- 0027 data preflight + mutable backfill；
- 0028 retry-safe DB guards + dual-identity fact parent trigger。

这样即使 0027 因脏映射 fail-closed，0026 已完成的 MySQL DDL 不会导致重试再次 ADD COLUMN；0027 可在修复映射后安全继续。0028 的约束/index 创建前通过 introspection 判断是否已存在，降低中断重试风险。

## 4. DevelopmentFact 历史不重写

历史封存事实保留 V1 hash 字段集合，其中人员身份仍是 legacy bigint。新增 UUID 的事实使用 V2 hash 字段集合。

更正/撤销：

- parent 为 V1 且 legacy 可唯一映射 → successor 写 UUID + legacy，使用 V2 hash；
- parent 本身不 UPDATE；
- ORM lineage 校验 canonical-first；
- MySQL parent trigger 同样 canonical-first：当 parent/new 两边都有 UUID 时必须 UUID 相等，不能因为 legacy 数字碰巧相同而放过；只有至少一边还是旧历史行时才允许 legacy fallback。

## 5. 重复 legacy ID 的处理

`legacy_employee_id` 当前并非 HR03 唯一约束，因此 Round9 不把它当可靠 Authority：

- numeric lookup：重复即 `STAFF_IDENTITY_AMBIGUOUS`；
- UUID lookup：若其 legacy bridge 在同租户重复，同样不允许悄悄使用；
- 0027：任何需要回填的 legacy ID 缺失或重复，整批回填前阻断；
- HR09 public evidence：重复 bridge 返回 `SOURCE_IDENTITY_MAPPING_AMBIGUOUS`；
- HR11：identity 缺失/歧义返回 SOURCE_UNAVAILABLE；
- Dashboard：历史 legacy fact 无法唯一映射时，不输出误导性的平均学时。

## 6. 新写入路径

已改为 canonical UUID：

- PlanService.create_plan；
- create_request；
- EnrollmentService.enroll / waitlist；
- enterprise practice assignment；
- development output；
- verified completion → DevelopmentFact；
- DevelopmentFact correction/revocation successor；
- RiskCase；
- Excel individual plan target。

人员下拉值、发展档案路由及查询统一支持 UUID；旧数字 deep link 通过 resolver 保留兼容。

## 7. HR11 边界

HR11 仍使用旧 BigInteger。Round9 没有把 HR11 整域强改 UUID，而是在 `Hr11TimeConflictProvider` 明确适配：

`HR10 canonical UUID → tenant-scoped HR03 legacy mapping → HR11 bigint query`

没有唯一映射时返回 SOURCE_UNAVAILABLE，绝不当作 PASS。

这使 HR10 Authority 先正确，同时不破坏 HR11 现有数据结构。

## 8. Excel Round8 闭环继续成立

Round8 的 lease claim、真实 authority write、逐行回执、确认期二次冲突检查都保留。Round9 只升级个人计划人员身份：

- UUID 输入直接解析；
- 旧数字 ID 仅在同 tenant 唯一映射时接受；
- staging 保存 canonical UUID + compatibility legacy ID；
- confirm 时再次批量校验映射和 authority conflict；
- 正式 HrDevelopmentPlan 写 UUID。

更新后的 `check_hr10_import_contract.py`：20/20 PASS。

## 9. 审批安全

approve / return / reject 统一由 ApprovalService 在锁定最新申请行后执行 `_is_self_approval`。优先 canonical UUID，legacy actor id 仅作为旧账号映射兜底。API 层的判断不再是唯一安全边界。

## 10. 本轮实际验证

已执行并通过：

- HR10 Python AST：144 files / 0 error；
- HR10 import static gate：20/20；
- HR10 staff identity static gate：53/53；
- Round2～Round7 + Round9 pure unittest：159/159；
- Round9 identity pure unittest：5/5（已计入 159）。

Django 动态测试**没有通过/失败结论**，而是当前执行器缺依赖，实际错误为：

`ModuleNotFoundError: No module named 'django'`

已真实尝试：

- `python manage.py makemigrations --check --dry-run`
- HR10 import / HR11 / public identity / fact authority targeted TestCase

均在 Django import 阶段终止。证据：`HR10_ROUND9_DJANGO_MIGRATION_ATTEMPT_2026-09-16.log`。

## 11. 发布前阻断项

在真正有 Django 5.2.x + MySQL 8.4 的 QA 环境完成以下项目之前，不标记 RELEASED：

1. `makemigrations --check --dry-run` 必须 No changes；
2. `migrate --plan` 核对 0026→0027→0028 顺序；
3. 脏 legacy mapping 复制库演练 fail-closed 与修复后重跑；
4. 真实 MySQL 检查 7 个 identity check、canonical enrollment unique、fact UUID index、parent trigger；
5. 跑 HR10 targeted Django tests；
6. 验证 V1 fact hash 及 V2 successor；
7. UUID-only staff + HR11 无 legacy 场景必须 SOURCE_UNAVAILABLE；
8. 重复 legacy bridge 不得产生 HR09 证据串人；
9. Round8 Excel 并发租约与真写入回归仍通过。

## 12. 结论

Round9 已把 HR10 的人员身份从“旧 Employee 数字 ID 为事实主键”改为“HR03 UUID 为 Authority，旧 ID 仅做受控兼容桥”。这是数据契约修复，不是 UI 文案修复。源码层已经具备可继续进入 MySQL QA 的条件，但当前环境没有 Django，因此发布状态保持 NOT_RELEASED。
