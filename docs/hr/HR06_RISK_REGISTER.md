# HR06 RISK REGISTER（S0 基线复审 · 风险登记册）

> 依据：《06_HR06_人事异动_施工总册_终极版》§81（AI 禁止越界）+ 00 合同 + S0 代码复审。
> 等级：P0=阻塞封板；P1=必须阶段内缓解；P2=登记跟踪。
> 状态：OPEN / MITIGATED / CLOSED。

---

## 1. 领域语义风险

| ID | 风险 | 等级 | 缓解措施 | 状态 |
|---|---|---|---|---|
| R-01 | 把 HR06 做成"编辑员工页"，用单表单直接改受管字段 | P0 | 受管字段字典 `HrChangeFieldDefinition`；S9 旧表单 readonly；UI 走 Case 向导 | OPEN |
| R-02 | Future-dated 事件互相覆盖（9月调A、9月15日调B） | P0 | base_snapshot_version/base_effective_at + Rebase Service + `HARD_CONFLICT` | OPEN |
| R-03 | 批准即改 Current Assignment（生效日在未来） | P0 | `APPROVED_WAITING_EFFECTIVE` 状态 + Apply Service 到期/显式提前才生效 | OPEN |
| R-04 | 借调结束手工改部门，无 return relation | P0 | `HrTemporaryAssignmentLink` + RETURN_FROM_TEMPORARY + return_policy | OPEN |
| R-05 | 兼岗直接覆盖主岗 | P0 | ADD_SECONDARY 创建 CONCURRENT 段；one-primary DB 唯一约束 | OPEN |
| R-06 | RETURNED 与 REJECTED 混为一谈 | P0 | 状态机显式区分；RETURNED 可补正重交，REJECTED 终局 | OPEN |
| R-07 | 人员已离职/待离职仍生效未来调动 | P0 | Apply 前 revalidate 当前事实（HR03 status_as_of） | OPEN |
| R-08 | 岗位无空缺也能调入 | P0 | HR02 PositionGate reserve/commit + capacity 校验；禁 override 物理容量 | OPEN |
| R-09 | 目标学院无授权却能把人塞进目标学院 | P0 | TargetOrg approver 参与正式批准（Target Authorization） | OPEN |
| R-10 | Correction 与业务 Change 混同（录错当第二次调动） | P0 | `DATA_CORRECTION` 动作 + `HrChangeCorrection` 受控流程 + 高权限 | OPEN |
| R-11 | 直接删除已生效异动记录 | P0 | 禁 hard delete；RESCINDED 正式流程 | OPEN |
| R-12 | 已生效 snapshot 原地修改 | P0 | `HrChangeEffectiveSnapshot` checksum 不可变；correction 走受控流程 | OPEN |
| R-13 | 后续事件依赖未检查（撤销9月调动但10月调动依赖它） | P0 | Rescind 依赖检查 `DEPENDENT_CHANGES_EXIST` | OPEN |
| R-14 | 转岗与职称聘任混为一事 | P1 | POST_CATEGORY_CHANGE 只改岗位类别；聘任归 HR14；不抢权威 | OPEN |
| R-15 | 组织调动与薪酬变化绑死成不可拆动作 | P1 | 薪酬只发 `CompensationRecalculationRequested`，不自建 | OPEN |
| R-16 | 临时返岗时原岗位已被组织重组撤销 | P0 | `RETURN_TARGET_INVALID` → human resolution → 新返岗目标 + 审批 | OPEN |
| R-17 | 用 is_active 代表异动状态 | P0 | 完整 Case 状态机；禁 boolean 替代 | OPEN |
| R-18 | 用 simple-history 代替业务台账 | P1 | `HrChangeTransition` + `HrChangeEffectiveSnapshot` | OPEN |
| R-19 | 台账与 HR03 facts 不一致 | P1 | as-of 互相验证 + S11 reconcile | OPEN |

## 2. 集成/技术风险

| ID | 风险 | 等级 | 缓解措施 | 状态 |
|---|---|---|---|---|
| R-20 | HR02 岗位占用/释放未联动 | P0 | Apply 事务内 reserve/commit/release；同一事务或可补偿 saga | OPEN |
| R-21 | 变更后 HR03 与 Horilla WorkInformation 不一致 | P0 | Legacy Projection（S9）+ DUAL_WRITE_COMPARE（S10） | OPEN |
| R-22 | 通过 Excel 直改当前字段绕过 Change Service | P0 | 导入模板移除受管字段列（S9 封堵） | OPEN |
| R-23 | 批量异动一个 SQL UPDATE | P0 | `HrBulkChangeBatch/Item` 逐人 Case；禁批量 UPDATE | OPEN |
| R-24 | 批量部分失败原子性 | P1 | PREVALIDATE_ALL + ATOMIC_BATCH/ITEMIZED_COMMIT + error workbook + retry | OPEN |
| R-25 | 审批并发（两个管理员同时 approve） | P0 | Case 行锁 + 状态机转移原子性 + approval snapshot 重检 | OPEN |
| R-26 | 两个案件抢同一岗位最后额度 | P0 | HR02 `reserve` 行锁 + idempotency_key（case_id） | OPEN |
| R-27 | Scheduler 与人工 Apply 同时执行 | P0 | 状态条件更新（APPLYING 原子转移）+ 行锁 | OPEN |
| R-28 | Downstream 同步失败回滚已真实生效人事事实 | P0 | Change=EFFECTIVE + Downstream=PARTIAL_FAILED；自动重试 + 人工修复（总册 §50） | OPEN |
| R-29 | 自动 fallback 到 legacy current state | P0 | 禁 silent fallback；显式 authority_mode + audit | OPEN |
| R-30 | Outbox 事件重复投递/丢失 | P1 | eventId 幂等 + 同事务 outbox + 重试（照抄 HR03/HR05） | OPEN |
| R-31 | 未来事件审批后 workflow 配置变化影响已提交案件 | P1 | `HrChangeApprovalSnapshot` 冻结 | OPEN |
| R-32 | case_no 并发冲突 | P1 | 行锁序列（照抄 HrStaffNumberSequence） | OPEN |
| R-33 | 前端用隐藏代替权限 | P0 | 服务端 ScopeEnforcer + 权限校验，前端仅展示 | OPEN |

## 3. 安全/合规风险

| ID | 风险 | 等级 | 缓解措施 | 状态 |
|---|---|---|---|---|
| R-34 | 学校 A 读到学校 B 数据 | P0 | 所有 HR06 表 tenant_id + 查询首条件 tenant + fail-closed | OPEN |
| R-35 | 学院 A 人事批准调往学院 B | P0 | target authorization + scope 校验 | OPEN |
| R-36 | 普通员工读他人未来异动 | P0 | scope（SELF/ASSIGNED_CASES）+ IDOR 测试 | OPEN |
| R-37 | Correction/Rescind 权限过低 | P0 | `hr.change.correct/rescind` 高权限码 | OPEN |
| R-38 | ledger export scope 泄露 | P1 | export scope 校验 + 审计（照抄 HR03） | OPEN |
| R-39 | 旧 Legacy edit endpoint 绕过 authority | P0 | S9 封堵 + 测试 | OPEN |
| R-40 | 后台 Job tenant 逃逸 | P1 | Job 显式 tenant context（00 §59） | OPEN |
| R-41 | 敏感信息经 Change API 泄露（证件/银行卡/健康） | P0 | Change API 只返回 staffNo/name/当前组织岗位/必要身份类别（总册 §44） | OPEN |

## 4. 质量/交付风险

| ID | 风险 | 等级 | 缓解措施 | 状态 |
|---|---|---|---|---|
| R-42 | 为绿 CI 跳测试/mock downstream 冒充完成 | P0 | 每阶段真实跑测试并报告通过/失败数 | OPEN |
| R-43 | 前端文案不中文 | P1 | labels.py 成对 label + Django i18n；test_i18n_labels | OPEN |
| R-44 | 目标库（MySQL）语义差异 | P1 | 00 §26 MySQL-only；迁移/FK/唯一/索引在 MySQL 全绿 | OPEN |
| R-45 | 台账 100 万事件分页性能 | P2 | 索引（tenant,status）/（staff,effective_at）等 + 禁 N+1 | OPEN |
| R-46 | HR07 并行施工冲突（同一仓库未提交改动多） | P1 | 独立分支 feature/hr06-changes；只 add 自己文件；不碰他人改动 | OPEN |

## 5. 已识别已关闭/历史教训（作为设计约束）

| ID | 教训 | 落地约束 |
|---|---|---|
| R-C1 | 直接用日期减一天做区间关闭 | 统一 `[effective_from, effective_to)` 半开（总册 §21.3） |
| R-C2 | 组织名历史解析散落各模块 | 委托 HR02 `org_version_as_of`；HR06 不自己拼日期条件 |
| R-C3 | 主岗唯一性只靠 service | DB 条件唯一约束 + service 行锁双重保障（对齐 HR03） |
| R-C4 | 幂等只靠前端按钮 | 写接口 `Idempotency-Key` + source_business_id 幂等键 |

---

**状态说明：S0 物化时全部 OPEN；各阶段施工完成且测试通过后逐项 MITIGATED，S12 封板时全部 CLOSED 或明确残余。**
