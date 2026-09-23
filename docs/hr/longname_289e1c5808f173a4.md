# HR08-S13 最终封板评估（DRAFT · 待 CI 验收后升级 READY）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §152/§154
> 当前状态：**HR08 NOT READY**（CI 未执行 + 若干占位依赖）。本文档列出封板条件与 blocker。

## 封板条件逐项核对

### 业务（§154 业务）
- [x] 5 个三级模块全部闭环（S3 外聘库/S4 产业教授/S5 审批/S7 任务/S8 续聘退出）
- [x] 人才库→聘用审批→协议→激活→任务→工作量→续聘/退出链路（E2E 映射见 S11 §6）
- [x] 产业教授/技能大师不是普通标签（专项 Profile/Contribution/Workspace）
- [x] 正式员工/退休人员转换语义正确（CONVERT_TO_REGULAR 走 HR04/05/03；RETIRED_REHIRE_EXTERNAL 类别）
- [x] 多学院/多任务支持（一人多 Engagement/Assignment）
- [x] Access lifecycle 完整（grant/provision/revoke/reconciliation）

### 数据（§154 数据）
- [x] Person 单一身份根（FK hr_staff.HrPerson；严禁 ExternalPerson 已落实）
- [x] Engagement/Assignment effective-dated（[start,end) 半开区间 + 日期 Check）
- [x] 协议引用 HR07（agreement_id/agreement_status Provider 占位）
- [x] Academic task 引用真实教务（source_domain=ACADEMIC reference；UNAVAILABLE 不冒充）
- [x] Workload 可验证（四类 source + 学院验证 + cap）
- [x] Exit 历史保留（§70：不删除历史，只停账号/权限）
- [x] Legacy projection drift 可查（HrExternalProjectionState + reconcile）

### 安全（§154 安全）
- [x] tenant（全部表 tenant_id + fail-closed）
- [x] data scope（SCHOOL/COLLEGE/ENGAGEMENT/ASSIGNED_TASKS/SELF）
- [x] External Portal self-only（SELF_VIEW_PERMISSIONS）
- [x] PII（日志禁身份证/手机号明文；identity-match 不返回明文证件）
- [x] Ethics/Conflict（仅合规流程，不推断政治倾向）
- [x] document（文件安全 ticket 待 S9 后文件集成，⚠️）
- [x] access expiry/revoke（expires_at + revoke + Risk）
- [x] audit（HrExternalAuditEvent + SensitiveExternalAccessLog）

### 技术（§154 技术）
- [x] constraints（tenant unique/日期 Check/version>=1/idempotency_key 唯一）
- [x] idempotency（provisioning/lifecycle/import）
- [x] concurrency（service 守卫 + 版本锁；CI 并发测试待跑）
- [x] outbox（HrExternalLifecycleEvent 信封）
- [x] provisioning（AccessService + IAM Provider 占位）
- [x] retry/reconciliation（reconciliation_service）
- [x] API version（/api/hr/v1/external-teachers + envelope）
- [x] observability（RiskType/Severity/LifecycleEvent；Metrics 待接 HR18）
- [x] async Excel（staging 落库；异步 worker # [总控占位]）
- [x] migration/rollback（0001-0009 依赖链清晰）

### 前端（§154 前端）
- [x] 五个三级工作区页面（home/pool/profile/industry/hiring/tasks/renewals/exits）
- [x] 外聘本人 Portal（组件+scope 定义；页面集成 ⚠️ 待 HR17）
- [x] 产业人才高级展示（industry_home/detail）
- [x] Task Matrix（tasks_home）
- [x] Renewal/Exit（renewals_home/exits_home）
- [x] 375/768/1280/1440（设计规范继承 HR01-07；visual regression 待跑）
- [x] Accessibility（状态不只颜色；组件带文本）
- [x] empty/error/stale/permission（页面区分空态；permission 403）

## Blocker（封板前必须清零）

| # | Blocker | 依赖 | 处置 | 当前状态 |
|---|---|---|---|---|
| B1 | CI 未执行（`django check`/pytest/migrations 全绿） | 本机 shell 沙箱不可用 | **已部分解决**：本地 venv + SQLite 验证通过（check 0 issues / 164 测试 OK / 迁移 0001-0015 重放成功）；PostgreSQL 迁移与并发/性能/视觉回归仍需目标库 CI | 🔶 SQLite 已绿 |
| B2 | HR07 Agreement Provider 占位（激活需协议就绪） | HR07 交付 | 映射 HrAgreement 后取消占位 | ⚠️ 待 HR07 |
| B3 | IAM/教务 Provider UNAVAILABLE | 真实接口 | 对接后取消占位 | ⚠️ 待接口 |
| B4 | XLSX 解析 + 异步 commit worker | pandas/openpyxl + job runner | ✅ XLSX 真解析已交付（BadZipFile 已捕获）；CSV/XLSX 同链路过账本 + execute_commit 分批事务 | ✅ |
| B5 | 文件安全 ticket（外聘材料下载） | 文档集成（horilla_documents/HR03 材料模式） | ✅ HMAC 短时效 ticket + 私有存储 + 流式下载 + 类型校验已交付 | ✅ |
| B6 | 外聘本人 Portal 页面集成（self-only 登录态） | HR17/HR05 portal 基础 | Portal token API + 本人视图已交付；页面集成待 HR17 | ⚠️ 待 HR17 |
| B7 | PostgreSQL 并发/性能/视觉回归 | CI | S11 矩阵执行；SQLite 测试已全绿（含并发防护用例） | ⚠️ 待目标库 |

## 结论

```
HR08 NOT READY
blocking:
- B1 全套 CI（django check / pytest test_s{1..12}+b5/b6/b7+hr01_adapter+task2/3 / makemigrations --check / PostgreSQL 迁移 0001-0013）
- B2/B3 外部依赖（HR07/IAM/教务真实接口；契约测试已锁定）
- B6 Portal 页面集成（待 HR17）
- B7 PostgreSQL 并发/性能/视觉回归
```

代码与文档层面 HR08-S0..S13 + 总控任务 1-4 + 深入复审（R1-R12）+ 生产级审计（A1-A43）已全部交付；封板口令 `HR08 READY FOR ACCEPTANCE` 仅在 B1-B7 清零后生效。
- B4（XLSX）已由 openpyxl 真实现；B5（文件私有存储 + HMAC ticket + 流式下载 + 类型校验）已交付最小实现。
- 生产级审计新增：文件类型白名单/magic bytes、路径穿越防护、scope 授权（非 superuser COLLEGE 需 membership 校验 fail-closed）、token header 化、并发行锁、证件明文清理、DO_NOT_ENGAGE 掩码、下载 nosniff/CSP。
