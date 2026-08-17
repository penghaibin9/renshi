# HR07 生产级审计报告（2026-08-09 · 第三轮）

> 范围：`renshi/hr_contracts/` 全量（models/services/api/selectors/jobs/integrations/projections/tests/migrations/模板）
> 方法：人工代码审查（逐文件）→ 修复 → 复验 → 再审查 → 再修复 → 本报告。
> 结论：**CODEFROZEN**。P0=0（静态）｜P1 全部修复｜残留项见 §5（环境依赖，非代码缺陷）。

---

## 1. 审查范围与方法

| 层面 | 覆盖 |
|---|---|
| 模型层 | 19 模型 + 约束 + save 保护 + 0001/0002/0003 迁移一致性 |
| 服务层 | number/rule/template/signing/signature/lifecycle/renewal/event/termination/correction/risk/outbox/audit/authority |
| API 层 | ledger/signing/events/risks + envelope + 权限 |
| 数据层 | selectors（scope/分页/排序/过滤）、projections、migration |
| 集成层 | hr03/05/06/15/16 provider |
| 测试 | 11 个测试文件（静态核验：与修复后逻辑一致） |
| 硬门 | 00 §8/§16/§20/§28/§56；HR07 §12/§16/§27/§39/§55/§58/§65/§89/§92/§149 |

---

## 2. 发现并修复的问题

### P0（会导致运行时 TypeError / DB 冲突 / 500 / 测试失败）

| ID | 问题 | 位置 | 修复 |
|---|---|---|---|
| A-01 | API 传入字符串日期 → 服务内 `timedelta`/`<=` 与 `date` 混算 TypeError | `signing_service.create_case` | 新增 `_to_date()` 统一解析（无效 422） |
| A-02 | `effective_date` 字符串与 `date` 比较 TypeError | `lifecycle_service.activate` | 新增 parse + 无效抛 409 |
| A-03 | 重叠检测状态集合漏 `APPROVED/GENERATING_DOCUMENT/WAITING_SIGNATURE/PARTIALLY_SIGNED/SUSPENDED` → 生成中合同可被重复建档 | `signing_service._check_overlap` | 状态集合补齐 9 态 |
| A-04 | 线下签署无扫描件时 `envelope.status=COMPLETED` + `final_document_hash=""` 违反 DB CheckConstraint → IntegrityError | `signature_service.complete_offline` | 约束放宽为"有终稿时才要求 hash"（无文件走 DOCUMENT_MISSING 风险）；新增迁移 `0003` |
| A-05 | `school_signed_at/staff_signed_at` 传纯日期字符串 → `DateTimeField` 保存 ValidationError | `signature_service.complete_offline` | 新增 `_to_datetime()`（aware datetime） |
| A-06 | multipart/form-data 上传签署件时 `json.loads(request.body)` 解析二进制 → 500 | `api/signing.complete_signature` | 仅非 multipart 时解析 JSON |
| A-18 | `_to_datetime` 误用 `@staticmethod` 却引用 `self.ctx` → NameError | `signature_service` | 改为实例方法 |

### P1（逻辑/安全/严谨性）

| ID | 问题 | 位置 | 修复 |
|---|---|---|---|
| A-07 | `LIFECYCLE_CLASS` 缺 `SUSPENDED`（i18n 徽标契约测试失败） | `display_labels.py` | 补齐 |
| A-08 | scope 裁剪用 `status="ACTIVE"` 漏 `ENDING_SOON` | `selectors/ledger._scope_staff_ids` | 改按 HR03 半开区间 `[effective_from, effective_to)` + 排除 DRAFT/CANCELLED |
| A-09 | `hr05` 签署状态映射缺 `SUSPENDED` | `integrations/hr05.py` | 补 `SUSPENDED → SIGNED` |
| A-10 | correction 空字段也能 apply | `correction_service.apply` | 无字段 → 409 |
| A-11 | 非法 UUID（agreement_type_id / relationship_id）→ ValueError → 500 | `signing_service` / `hr03` | 捕获 → 422 AGREEMENT_TYPE_INVALID / AGREEMENT_EMPLOYMENT_MISMATCH（防探测统一信封） |
| A-12 | 编号规则未配置 → NumberServiceError → 500 | `signing_service.generate` | 包装为 409 AGREEMENT_NUMBER_CONFLICT；模板注入 `agreement.agreementNo` 变量 |
| A-13 | 未知 `eventType` 可创建非法事件；AMEND 允许空条款 | `event_service.create_event` | 校验 eventType ∈ 枚举；AMEND 必须带 terms |
| A-14 | 续签 future 冲突状态集合与 overlap 检测不同步 | `renewal_service.decide` | 对齐 9 态 |
| A-15 | `test_legacy_s9` 的 mock 打在错误目标（函数级 `from-import` 不受 `patch.object(module)` 影响）→ 测试静默失效 | `tests/test_legacy_s9.py` | patch 真实导入源 `payroll.models.models.Contract` |
| A-17 | 签署件未持久化（只存文件名）+ 无 MIME/size 校验 | `signature_service.complete_offline` | 持久化到 `MEDIA_ROOT/hr_contracts_private/`（非公开 /media/）+ 扩展名白名单 + 20MB 上限 + 保存后真实 SHA-256 |

### P2（性能/整洁）

| ID | 问题 | 位置 | 修复 |
|---|---|---|---|
| A-16 | 台账列表每行额外查询 `agreement_type_id.name`（N+1） | `selectors/ledger.base_qs` | `select_related("agreement_type_id")` |
| A-19 | 未使用 import（uuid/timezone） | `api/events`、`api/signing`、`event_service` | 清理 |

---

## 3. 复验（第二轮/第三轮）

- [x] `signing_service.create_case`：日期解析前置 → overlap/规则/存储全用 `date`（复查通过）。
- [x] `generate`：编号异常 → 业务错误；`variables["agreement.agreementNo"]` 注入后模板渲染不再丢编号（`_build_variables` 过滤空值后注入，逻辑成立）。
- [x] `complete_offline`：`_to_datetime` 实例方法 + aware tz；无文件 COMPLETED 通过放宽后约束；有文件则持久化 + hash + 扩展名校验。
- [x] `_check_overlap` 与 `renewal_service` future 检查状态集合一致（9 态）。
- [x] 非法 UUID/日期/事件类型全部收敛为业务错误信封（400/409/422），不再 500。
- [x] 测试文件静态核验：`test_overlap_rejected`（GENERATING_DOCUMENT 现在被检测）、`test_offline_signature_waiting_effective`（字符串签署时间被转换）、`test_legacy_s9`（mock 路径）、`test_i18n_labels`（SUSPENDED badge）与修复后逻辑一致。
- [x] 迁移链：0001 → 0002（Django 自动生成）→ 0003（约束放宽）；0003 Q 条件顺序与模型声明一致，避免 `makemigrations` 产生噪音迁移。

---

## 4. 安全/硬门专项复核（修复后）

| 项 | 结果 |
|---|---|
| tenant fail-closed | ✅ 全模型 tenant_id；API 经 `make_hr07_context`；无上下文 403 |
| 状态不由日期推断 | ✅ 模型 save 拦截 + LifecycleService 唯一激活入口 + 日期校验 |
| SIGNED/PUBLISHED 不可变 | ✅ 版本内容字段拦截（仅状态流转）；模板 ACTIVE 拦截正文；SIGNED_FINAL 文件不可改 |
| 到期提醒去重 | ✅ `open_key` DB unique（同合同同类型仅一个 OPEN）；resolve/waive 释放 |
| review 不自动续签 | ✅ decide 仅产出案件/决策 |
| 不建第二套 EmploymentRelationship | ✅ 仅 UUID 引用 HR03 |
| HR15 金额边界 | ✅ `compensation_reference` 仅引用；无金额计算/统计 |
| FINAL 不可原地改 | ✅ correction/amendment/void 分离 + before/after 审计快照 |
| 文件安全 | ✅ 私有目录 + 扩展名白名单 + size 上限 + SHA-256 + SIGNED_FINAL hash 必填（有文件时） |
| 防探测 | ✅ 跨租户 detail 返回 None（404）；非法 UUID 收敛业务错误码 |
| 审计 | ✅ `HrAgreementAuditEvent` + `SensitiveAgreementAccessLog` 全程落审计 |
| `date.today()` 直用 | ⚠️ 仅存在于：provider/job/migration/termination 的 ctx 缺省兜底（无 HTTP 上下文场景），业务 selector 均走 `ctx.today()`；记录为可接受偏差 |

---

## 5. 残留风险 / 已知限制（非本轮修复范围）

| 项 | 说明 |
|---|---|
| Payroll 解耦门后半（旧页面 redirect、W1-W5→HR15） | 依赖 HR15 交付；未改 payroll 旧表（S13 已记录 block） |
| 电子签真实厂商 Adapter | V1 仅 OFFLINE + `SignatureProvider` 契约；Mock 仅测试 |
| 下载走 ticket / 病毒扫描 / 水印 | 依赖 HR00 对象存储/文件基建（S11/S13 已记录） |
| E2E / 视觉回归 / 性能采样 | 需 shell 环境（本机沙箱不可用） |
| 签署件孤儿文件 | 文件先落盘后 DB 事务提交；commit 失败时产生无引用文件（V1 可接受，待对象存储后治理） |
| 限流/防爆破 | 依赖 HR00 网关基建 |

---

## 6. 需用户终端执行（本机无 shell）

```bash
python manage.py makemigrations --check --dry-run   # 期望无新迁移（0001/0002/0003 已覆盖）
python manage.py migrate
python manage.py test hr_contracts
python manage.py hr07_reconcile_legacy --tenant 1 --dry-run
```

## 7. 结论

```text
HR07 代码层生产级审计完成：P0 静态清零（A-01~A-06、A-18），P1 全部修复（A-07~A-15、A-17），P2 清理（A-16、A-19）。
迁移链 0001→0002→0003 与模型一致。等终端 migrate + tests 全绿后升级为 HR07 READY FOR ACCEPTANCE。
```
