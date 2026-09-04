# 核心业务流程 100% 验收总册

> 文件：`CORE_BUSINESS_FLOW_ACCEPTANCE.md`  
> 版本：V1.0｜2026-09-04  
> 适用范围：HR01～HR18、真实 MySQL、真实角色、真实浏览器、跨域服务合同与生产发布  
> 定位：本文件是“核心业务流程必须 100% 通”的唯一计算口径；不替代各 HRxx 业务总册，也不允许模块报告另造更宽松标准。

## 1. 一句话标准

```text
一个真实学校 + 一个真实组织 + 一个真实岗位/编制 + 一个黄金候选人/教职工
+ 多个真实业务角色
```

必须把下面主线连续走通：

```text
HR01 工作台
→ HR02 组织/岗位/编制
→ HR04 招聘/候选人/拟录用/公示/Offer
→ HR05 入职报到/材料/激活
→ HR03 教职工主档/聘用关系/任职
→ HR07 合同签署/生效
→ HR06 调岗等人事异动
→ HR08/HR09 外聘与资格
→ HR10 培训发展
→ HR11 考勤请假
→ HR12 年度/聘期考核
→ HR13 职称评审
→ HR14 岗位聘任
→ HR15 薪酬福利
→ HR16 退休/离校
→ HR17 本人回读
→ HR18 指标/快照/报表/归档
```

如果只能打开页面、查看 mock、出现 toast，不能形成持久状态变化、下一角色回读和历史证据，结论就是 **FAIL**。

---

## 2. 100% 如何计算

### 2.1 必需项

```text
正向人工/浏览器 Case：HM-HR-00～HM-HR-15，共 16 项
安全与一致性负例：N-HR-01～N-HR-08，共 8 项
自动化生产 Gate：本文件第 8 节全部必需项
```

### 2.2 计算公式

```text
人工业务通过率 = PASS 的 HM 数 / 16
负例通过率     = PASS 的 N 数 / 8
```

只有同时满足下面条件，才允许写 `CORE BUSINESS FLOW = 100% PASS`：

```text
HM-HR-00～15 = 16/16 PASS
N-HR-01～08  = 8/8 PASS
必需自动化 Gate = 全部 PASS
BLOCKED = 0
SKIPPED = 0
P0 = 0
阻断核心主链的 P1 = 0
全部证据绑定同一 Product exact SHA
```

`BLOCKED`、`SKIPPED`、`NOT RUN` 均按未通过计算；不允许从分母删除难测项。

---

## 3. 固定黄金数据集

每次正式验收使用隔离、可重复创建的数据集；名称可以带时间戳，但业务关系必须固定。

| 对象 | 最低要求 |
|---|---|
| Tenant A | 验收学校，包含人事、学院、审批、专家、薪酬和数据角色 |
| Tenant B | 越权负例学校，拥有独立组织和人员 |
| Organization A | 黄金学院/部门 |
| Position A | 初始教师岗位，至少 1 个可用编制 |
| Position B | 调岗目标岗位，容量有限 |
| Candidate A | 黄金候选人，最终成为 Employee A |
| Employee B | 同租户另一名教职工，用于本人端越权负例 |
| Candidate B | 并发争抢最后一个编制的第二候选人 |
| Contract A | Employee A 的正式合同 |
| Test period | 考勤、考核和薪酬可独立封账的验收周期 |

数据要求：

- 禁止使用生产真实个人数据；使用合成姓名、证件号、邮箱、工资和附件。
- 所有对象必须带 tenant、创建人和可追踪业务编号。
- 固定数据准备脚本只能创建前置数据，不能越过用例中的正式业务动作直接写最终状态。
- 重跑前必须确认上一轮数据已隔离或使用新的业务编号，不能因残留数据制造假通过。

---

## 4. 固定角色

| 角色 | 主要职责 |
|---|---|
| HR Admin | 人事处实务、组织岗位、招聘、入职、合同、异动、离校 |
| Department User | 用人需求、到岗确认、评价、交接 |
| Candidate / Employee | 报名、Offer、入职材料、本人自助、申报与自评 |
| Expert / Reviewer | 面试、资格、考核、职称、聘任评议 |
| Approver | 编制、录用、入职、合同、异动、考核、聘任、离校决策 |
| Payroll User | 薪酬核算、复核、发放与对账 |
| Data User | HR18 指标、快照、报表、上报、回执和修正 |
| Tenant B User | 跨租户负例，不得获知 Tenant A 对象是否存在 |

同一个超级管理员代替所有角色只能用于开发定位，不能作为正式跨角色 UAT 签字。

---

## 5. 每一步统一按“5 看 + 6 查”

### 真人必须“5 看”

1. **看入口**：当前角色是否看得到且名称明确；无权限入口不虚假展示。
2. **看动作**：按钮、字段、附件、选择范围、确认提示与业务前置条件正确。
3. **看结果**：不能只看 toast；刷新、重新进入、重新登录后状态仍正确。
4. **看另一端**：下一角色、本人端、审批端读取的是同一业务事实。
5. **看历史**：退回、补交、变更、调岗、追补、离校后旧事实仍可追溯。

### 工程验收必须“6 查”

1. **查 HTTP/server truth**：状态码、响应、request_id、服务端最终结果。
2. **查 MySQL**：唯一约束、事务、状态、外键、时间边界和 tenant。
3. **查权限**：角色、对象、部门、tenant、导出与附件访问范围。
4. **查审计**：actor、动作、前后状态、原因、时间、请求或事件关联。
5. **查异步/外部回执**：Outbox、幂等键、重试、真实 receipt、失败风险。
6. **查并发/重放**：重复点击、重复回调、最后一个容量、死锁重试。

---

## 6. 正向黄金 Case｜HM-HR-00～15

### HM-HR-00｜登录、租户、菜单、刷新与深链

**角色：** HR Admin、低权限用户、Tenant B User。

**操作：**

1. 使用真实登录表单进入 Tenant A。
2. 确认当前学校、当前角色和数据范围。
3. 进入 HR01～HR18 中当前角色应见入口。
4. 刷新、复制深链重新打开、退出后重登。
5. 使用低权限和 Tenant B 账号重复关键入口检查。

**PASS：**

- 租户上下文正确；刷新与深链不丢失。
- 正确角色能进入；无权限入口不显示或进入后明确拒绝。
- 空数据是真实空态，无 mock 统计。
- 页面无 5xx；403 只出现在应拒绝场景。
- 登录、失败尝试和关键访问有审计/安全记录。

---

### HM-HR-01｜HR02 建组织、岗位和编制

**角色：** Department User → HR Admin → Approver。

**操作：**

1. 创建/选择 Organization A。
2. 创建 Position A、岗位职责和有效期。
3. 创建并提交 HeadcountPlan/容量。
4. 审批通过。
5. 刷新回读当前容量，并按生效日前后做 as-of 查询。

**PASS：**

- 组织、岗位、编制是独立且关联的真实对象。
- 审批前后状态明确，生效时间可解释。
- 后续 HR04 必须选择 Position A，不允许手填孤立岗位名称。
- Department User 只处理本部门数据。
- 历史结构不因后续修改消失。

---

### HM-HR-02｜HR04 创建招聘需求、批次和职位

**角色：** Department User → HR Admin。

**操作：**

1. 从 Position A 发起用人需求。
2. 创建招聘批次/职位并绑定真实编制。
3. 提交并发布职位。
4. Candidate A 从候选人入口查看并报名。
5. 测试无编制、未生效岗位、重复发布等异常。

**PASS：**

- 招聘与 HR02 真实岗位/容量相连。
- 候选人只看到公开且有效的职位。
- 无编制或不合法岗位不能进入假招聘成功。
- 发布、撤回、重新发布均有状态和审计历史。

---

### HM-HR-03｜候选人材料、筛选、评议、拟录用、公示与 Offer

**角色：** Candidate A、HR Admin、Expert、Approver。

**操作：**

1. Candidate A 填写资料并上传合成附件。
2. HR Admin 做资格审查；至少走一次退回补交。
3. Expert 完成考试/面试/评议。
4. 形成拟录用并审批。
5. 完成公示且无阻断异议。
6. 发出 Offer，Candidate A 接受。

**PASS：**

- 退回原因和补交版本保留。
- 未满足任何前置条件时不能越级 handoff。
- Expert 只能处理分配任务。
- Offer 接受结果刷新后仍可读。
- 附件经过授权、类型/大小和恶意文件扫描。

---

### HM-HR-04｜HR04 → HR05 正式 handoff

**角色：** HR Admin / 系统。

**操作：**

1. 对 Candidate A 执行进入入职。
2. 在 HR04 刷新查看 handoff 状态。
3. 在 HR05 查到同一个候选人的 OnboardingCase。
4. 连续点击或重试 handoff。
5. 模拟 consumer/provider 一次失败后重试。

**PASS：**

- 只生成一个有效 OnboardingCase。
- PositionReservation 仍是 `HELD`，未提前冒充正式占编。
- HR04 成功与 HR05 事实一致；下游失败不能显示假成功。
- 重放使用稳定幂等键，审计可关联同一业务请求。

---

### HM-HR-05｜HR05 报到、材料核验、到岗确认

**角色：** Candidate A、Department User、HR Admin。

**操作：**

1. Candidate A 填写入职信息并上传材料。
2. Department User 确认到岗/岗位接收。
3. HR Admin 核验材料。
4. 故意缺少一项必需材料尝试办结。
5. 退回、补齐并重新提交。

**PASS：**

- 缺材料或未到岗时不能激活。
- 候选人、部门、人事对当前状态理解一致。
- 原附件、补交附件、退回原因和操作人可追溯。
- 失败不产生正式 Staff 或 COMMITTED 占编。

---

### HM-HR-06｜HR05 激活 HR03 并正式占编

**角色：** HR Admin → Approver / 系统。

**操作：**

1. 对满足条件的 OnboardingCase 执行 activation。
2. 在 HR03 查询 Candidate A 转成的 Employee A。
3. 核对 Person、Staff、EmploymentRelationship、Primary Assignment。
4. 在 HR02 核对 PositionReservation 从 `HELD` 变为 `COMMITTED`。
5. 重复 activation。

**PASS：**

- 只形成一套正确人员事实链。
- Primary Assignment 指向 Position A。
- 占编只在正式激活后提交。
- 重放不产生第二个人、第二聘用关系或第二主岗。
- 任一中间失败均回滚或形成可恢复、可解释状态。

---

### HM-HR-07｜HR07 合同起草、审批、签署、生效

**角色：** HR Admin → Employee A → Approver。

**操作：**

1. 从 Employee A 的 EmploymentRelationship 创建 Contract A。
2. 选择模板、期限和相关岗位信息。
3. 提交审批。
4. Employee A 查看并确认/签署。
5. Approver 使合同生效。
6. 刷新、重登并从 HR17 回读。

**PASS：**

- 合同绑定现有 EmploymentRelationship，不另造人员关系。
- DRAFT、APPROVED、SIGNED、EFFECTIVE 状态边界清楚。
- SIGNED/EFFECTIVE 后普通编辑拒绝。
- 本人端读取同一合同事实和版本。
- 合同文件授权、哈希/版本和审计完整。

---

### HM-HR-08｜HR06 调岗与历史保留

**角色：** Department User、HR Admin、Approver。

**操作：**

1. 建立容量有限的 Position B。
2. 为 Employee A 发起 effective-dated 调岗。
3. 校验并预留 Position B。
4. 审批并在生效时点执行。
5. 查看当前 Primary Assignment、原 Assignment 历史、Position A/B 容量。
6. 查看 Contract A 是否被静默修改。

**PASS：**

- 目标岗位有合法容量后才生效。
- 原 Primary Assignment 被关闭而非删除；as-of 仍可读。
- 新 Primary Assignment 成为当前事实。
- 目标预留 COMMITTED，原岗位按规则释放。
- Contract A 原文不变；需要处理时生成正式 ContractReviewRequired/变更链。
- 重复生效幂等，失败无半写。

---

### HM-HR-09｜HR08/HR09 外聘与资格/双师闭环

**角色：** HR Admin、Employee/External Person、Expert、Approver。

**操作：**

1. 走一条外聘需求、协议、身份、任务、续聘或退出链。
2. 验证 IAM/教务协同只有真实回执后才判生效。
3. Employee A 提交资格/双师材料。
4. 完成规则校验、专家复核、公示/生效。
5. 验证续期、撤销或失效后的历史。

**PASS：**

- External Engagement 不冒充正式 EmploymentRelationship。
- 外部边界失败、超时、回执丢失不会显示最终成功。
- 资格结论关联证据和规则版本，不是手填标签。
- Expert 任务范围正确；资格历史可追溯。

---

### HM-HR-10｜HR10 培训、进修或企业实践

**角色：** Employee A、Department User、HR Admin/Trainer、Approver。

**操作：**

1. 创建培养计划和项目/活动。
2. Employee A 报名并审批。
3. 记录过程、学时、成果或企业实践。
4. 上传并核验证据。
5. 完成后形成 `VERIFIED DevelopmentFact`。
6. 让 HR12 读取该正式事实。

**PASS：**

- 报名、过程、完成、核验状态不能越级。
- 学时/成果必须经核验后才进入正式事实。
- HR12 通过正式 Provider/Event 消费，不直接跨域改写。
- 取消、退回、重交和更正保留历史。

---

### HM-HR-11｜HR11 考勤、请假、异常更正与封账

**角色：** Employee A → Department User → HR Admin。

**操作：**

1. Employee A 提交请假。
2. Department User 审批。
3. 创建一条考勤异常。
4. Employee A/HR Admin 按规则更正。
5. 校验并关闭测试周期。
6. 封账后尝试普通修改。

**PASS：**

- 本人只能处理自己的记录。
- 审批结果刷新、重登后可读。
- 更正保留原始事实和更正事实。
- 周期封账后普通修改拒绝。
- HR12/HR15 只读取正式周期结果。

---

### HM-HR-12｜HR12 年度/聘期考核

**角色：** Employee A、Department User、Expert/Calibrator、HR Admin。

**操作：**

1. 创建 PolicyVersion 和考核周期。
2. 固化 Population/Evidence Snapshot。
3. Employee A 自评。
4. Department User、Expert 完成评价。
5. 校准、复核并 Finalize。
6. 尝试在 Finalize 后普通修改，再走正式 Revision/Appeal（如启用）。

**PASS：**

- 未定稿结果不进入 HR13/14/15 正式输入。
- 评价人与对象范围正确。
- Snapshot 可解释当时证据，不被后续事实静默改变。
- Finalized 后更正产生新版本/流程。

---

### HM-HR-13｜HR13 职称评审 → HR14 岗位聘任

**角色：** Employee A、Department User、Expert、HR Admin、Approver。

**操作：**

1. Employee A 发起职称申报。
2. 完成资格预审、专家评审、委员会评议、公示与生效。
3. 使用有效职称、考核等作为 HR14 聘任输入。
4. 完成学院意见、评议、集体决策和聘任生效。
5. 回读 HR03/HR15/HR18 的正式结果投影。

**PASS：**

- 职称与岗位聘任是两个独立 Authority、两套状态链。
- 专家只能处理分配任务。
- 公示/决策前不能提前生效。
- 历史职称和历史聘任任期可追溯。
- 下游只消费 EFFECTIVE 结果。

---

### HM-HR-14｜HR15 薪酬核算、复核、发放与追补追扣

**角色：** Payroll User、Approver/Finance、Employee A。

**操作：**

1. 创建测试薪酬周期。
2. 读取 HR03、HR11、HR12、HR14 等正式输入。
3. 核算并人工复核。
4. Finalize。
5. 发起 Payment Dispatch，接收真实/测试受控 Provider receipt 并对账。
6. Employee A 从 HR17 查看结果。
7. 形成一次追补/追扣。

**PASS：**

- Finalize 前后严格区分，金额为 Decimal。
- 未获可信回执不能显示已支付。
- 追补追扣形成差额事实，不改写已发历史周期。
- Employee A 只能看本人薪酬。
- HR18 成本口径与 HR15 Final 事实一致。

---

### HM-HR-15｜HR16 离校/退休 → HR17 本人 → HR18 数据归档

**角色：** HR Admin、Department User、Finance/Asset/IAM、Approver、Employee A、Data User。

**操作：**

1. 为 Employee A 发起 Exit/Retirement Case。
2. 完成部门交接、合同、薪酬、资产、IAM 等清退条件。
3. 审批并生效。
4. 在 HR03 查看关系关闭，在 HR14 查看聘任关闭，在 HR02 查看岗位/编制释放。
5. Employee A 从 HR17 查看可公开的离校/退休结果和证明。
6. Data User 在 HR18 生成 as-of Snapshot、指标、报表/导出。
7. 如启用上报，执行 Validate → Approve → Send → Receipt；再做一次 Correction。

**PASS：**

- 清退未完成时不能标记最终离校。
- HR03、HR07、HR14、HR15、HR02、IAM 结果一致。
- 原在职、合同、任职和薪酬历史仍可查。
- 岗位释放后才可再次招聘。
- HR17 只聚合本人有权看的正式事实。
- HR18 快照、回执、修正有版本；Correction 不覆盖原快照，也不反写源业务。

---

## 7. 必需负例｜N-HR-01～08

| Case | 操作 | PASS 标准 |
|---|---|---|
| N-HR-01 跨租户猜 ID | Tenant B 读取/修改 Tenant A 的岗位、人员、合同、工资、附件 | 拒绝且不泄漏对象是否存在；审计记录异常访问 |
| N-HR-02 最后一个编制并发 | Candidate A/B 同时争抢最后一个容量 | 最多一个最终成功；无超编、负容量、双 COMMITTED |
| N-HR-03 handoff/activation 重放 | 重复点击、重复回调、并发重试 | 只有一个有效 Case/Staff/Employment/Primary Assignment；响应可解释 |
| N-HR-04 错误部门/审批人 | 无 scope 的部门或错误审批角色处理对象 | 403/业务拒绝；状态与审计不被篡改 |
| N-HR-05 历史 Assignment | 调岗后查询调岗前 as-of | 原岗位关系仍能解释，未被删除或改成新岗位 |
| N-HR-06 已签合同不可变 | 对有 EFFECTIVE Contract 的员工调岗或普通编辑 | 原合同保持；需要变化走正式 review/amendment/renewal |
| N-HR-07 本人端越权 | Employee A 猜 Employee B 的合同、工资、档案、考核 | 拒绝且附件下载同样拒绝 |
| N-HR-08 HR18 反向写源 | 从报表、快照或 Correction 直接修改 HR03/HR15 历史事实 | 禁止；回源对应 Authority 或形成新版本事实 |

负例不得只在服务单测中模拟；至少关键越权、并发、重放和历史查询要在真实 MySQL 合同测试中证明。

---

## 8. 必需自动化 Gate

### 8.1 代码与 MySQL

- Python 语法、Ruff、Black、isort；
- Django system check 与 production deployment check；
- `makemigrations --check --dry-run`；
- MySQL 8.4 clean database fresh migrate；
- previous baseline → current 的真实升级；
- HR01～HR18 Authority gate；
- 所有注册 HR app tests；
- 关键并发、事务、幂等、tenant、scope 和不可变历史测试。

### 8.2 真实浏览器

至少执行并保留证据：

- `.github/workflows/hr-browser-flow.yml`；
- `.github/workflows/hr-w-a-handoff-browser.yml`；
- `.github/workflows/hr-w-b-browser.yml`；
- `.github/workflows/hr-w-b-external-contract.yml`；
- `.github/workflows/hr12-annual-browser.yml`；
- 本文件 HM-HR-00～15 尚未被现有脚本覆盖的状态动作。

浏览器门必须使用真实 MySQL、真实 Django、真实登录、真实 HTTP；禁止用静态 HTML 或直接调用服务代替全部真人路径。

### 8.3 Docker、恢复与安全

- Compose config/build/release/up；
- MySQL、Redis、ClamAV 与必需 worker healthy；
- Gunicorn `/health/`、`/ready/`；
- Trivy High/Critical gate；
- 加密备份生成与校验；
- 恢复到不同名称空库；
- 恢复库启动后抽查黄金教职工事实；
- 生产 `DEBUG=True`、弱密钥、错误外部边界、扫描器缺失等 fail-closed；
- 日志不泄漏密码、token、Cookie、身份证件和完整工资数据。

具体命令见 [`PRODUCTION_RUNBOOK.md`](PRODUCTION_RUNBOOK.md)。

---

## 9. xlsx、附件与审计必须进入核心验收

### xlsx

至少对组织/人员、招聘候选人、考勤、考核、薪酬或报表中的高频批量场景验证：

```text
模板下载
→ 字段/字典说明
→ 上传预校验
→ 错误行与错误原因
→ 用户确认
→ 写入
→ 重试幂等
→ 导入审计
→ 按 scope 导出
```

要求：

- 文件格式是真实 `.xlsx`，不是 CSV 改扩展名；
- 错误行可下载，不让用户手工猜；
- 批量失败不产生不可解释半写；
- 导出不能越租户/越部门；
- 大批量不得同步阻塞 Web 到不可用，应有任务状态、进度和失败明细。

### 附件

- 类型、MIME、大小、恶意文件扫描；
- 私有存储和对象级授权；
- 文件版本、哈希、上传人、引用对象与下载审计；
- 已进入正式决定/归档的证据不能被普通替换覆盖。

### 审计

每个关键写操作至少记录：

```text
request_id / event_id
actor / role
tenant / scope
aggregate / object id
action
before / after 或状态转换
reason
occurred_at
idempotency key（适用时）
provider receipt（适用时）
```

---

## 10. 证据记录格式

每个 Case 必须记录：

| 字段 | 内容 |
|---|---|
| Case | `HM-HR-xx` 或 `N-HR-xx` |
| Product SHA | 40 位 exact SHA |
| PR / branch | 例如 `#53 / fix/production-readiness-20260904` |
| 数据集编号 | Tenant、黄金员工、周期、业务编号 |
| 角色 | 当前操作者及数据范围 |
| 页面/URL | 实际入口或 API |
| 前置状态 | 可复现的业务前置条件 |
| 操作 | 真人执行动作 |
| 预期 | 本文件对应 PASS 标准 |
| 实际 | 页面、HTTP、MySQL、另一端、历史结果 |
| request_id / event_id | 可用于查日志和审计 |
| 结果 | PASS / FAIL / BLOCKED；禁止“基本通过” |
| 截图/录像 | 关键状态前后与另一端回读 |
| Actions / test | 对应 run/job 或测试名 |
| 缺陷 | Issue/PR、级别、修复 SHA、回归结果 |

失败时额外记录：

- 页面错误文字和 HTTP 状态码；
- 是否刷新可恢复；
- 是否产生半写、重复对象、超编、历史丢失或越权泄漏；
- 精准回归范围。

---

## 11. 缺陷分级

### P0

- 跨租户人员、合同、工资、档案或附件泄漏；
- 超编仍判成功；
- 一次入职产生重复正式 Staff/Employment；
- 已签合同或历史任职被静默篡改；
- 工资严重错算并 Finalize/发放；
- 离校后关系、岗位、账号、清算出现不可解释冲突；
- 关键事务产生不可恢复半写；
- 备份无法恢复且无可用替代。

### P1

- 任一 HM 主流程走不通；
- 正确角色被拒绝或错误角色可处理；
- HR04 显示 handoff 成功但 HR05 无 Case；
- HR05 显示激活成功但 HR03/HR02 无一致事实；
- 调岗丢历史；
- HR17 看不到应公开正式结果或能看他人数据；
- HR18 与源业务严重不一致或可反写；
- 退休/离校无法闭环；
- 必需 MySQL、迁移、Docker、浏览器或恢复 Gate 失败。

### P2

- 菜单/文案不清；
- 空态、错误态、下一步提示差；
- 操作路径重复但不阻断；
- 售前讲解不够直观；
- 非核心报表格式问题。

任何 P0 或阻断主链的 P1 都是 `NO-GO`。

---

## 12. 失败后的精准回归映射

| 出错位置 | 先重跑 |
|---|---|
| 登录/tenant/permission | HM-HR-00 + N-HR-01/04/07 + 受影响导出/附件 |
| HR02 | HM-HR-01/02 + N-HR-02 + HR05 占编 + HR06/16 容量回读 |
| HR04 | HM-HR-02～04 + handoff 前置负例 |
| HR05/HR03 激活 | HM-HR-04～07 + N-HR-03 |
| HR07 | HM-HR-07/08 + N-HR-06 + HR17 回读 |
| HR06 | HM-HR-08 + N-HR-02/05/06 |
| HR08/09/10 | HM-HR-09/10 + HR12 下游证据 |
| HR11 | HM-HR-11/12/14 + 封账不可变 |
| HR12 | HM-HR-12/13/14 + Finalized 版本 |
| HR13/14 | HM-HR-13/14 + 职称聘任分离 |
| HR15 | HM-HR-14/15 + 本人隔离 + receipt/追补追扣 |
| HR16 | HM-HR-15 + 岗位释放 + 本人/数据中心回读 |
| HR17 | HM-HR-07/14/15 + N-HR-07 |
| HR18 | HM-HR-15 + N-HR-08 |
| migration/设置 | fresh migrate + previous upgrade + 全部受影响 app tests |
| Docker/恢复 | production check + release + readiness + backup/restore |

修复后先跑精准链，再跑第 8 节全部生产 Gate；不能只跑原失败用例就签字。

---

## 13. 最终签字表

| 项目 | 结果 |
|---|---|
| Product exact SHA | `PENDING` |
| HM-HR-00～15 | `0/16` |
| N-HR-01～08 | `0/8` |
| Quality / MySQL Contract | `PENDING` |
| Previous Baseline / MySQL Upgrade | `PENDING` |
| Docker / MySQL Smoke | `PENDING` |
| Browser workflows | `PENDING` |
| xlsx / file / audit | `PENDING` |
| Backup / restore | `PENDING` |
| P0 | `PENDING` |
| Blocking P1 | `PENDING` |
| Reviewer / date | `PENDING` |

最终判定：

```text
全部为 PASS、HM=16/16、N=8/8、P0=0、Blocking P1=0
→ CORE BUSINESS FLOW = 100% PASS
→ 可以进入 PRODUCTION READY CANDIDATE 签字

否则
→ NO-GO
```
