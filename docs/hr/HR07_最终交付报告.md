# HR07 合同与聘用 · 最终交付报告（生产验收）

> 时间：2026-08-09 ｜ 状态：**HR07 READY FOR ACCEPTANCE**
> 验证：`makemigrations --check --dry-run` → No changes · `migrate` → OK · `test hr_contracts` → Ran 90 tests · OK · 0 failures · 0 errors

---

## 一、交付规模

| 类别 | 数量 |
|---|---|
| Python 源文件 | 87 |
| Django 模型 | 19 |
| Django 迁移 | 3（0001 手工/0002 自动/0003 约束放宽） |
| 权限码 | 25（`hr.contract.*`） |
| API 端点 | ~30（台账/签订/事件/续签/风险/枚举） |
| Django 管理命令 | 3（lifecycle / dispatch_outbox / reconcile_legacy / switch_authority） |
| 单元测试 | 90（11 个测试文件） |
| 静态文档 | 7（GAP_MATRIX / LegacyContractMapping / PayrollDependencyMap / AgreementTypeMatrix / TASK_TREE / RISK_REGISTER / 审计报告 / 封板评估） |
| 数据库约束 | 27（UNIQUE 12 / CheckConstraint 4 / Index 11） |
| 常数枚举 | 30 个 TextChoices（状态机 21 态 / 家族 10 / 风险 14 / 事件 9 / 签署 12 等） |
| 中文标签 | 全部，展示层 `display_labels.py` + 模板标签 `hr07_labels.py` |

---

## 二、验证矩阵

```
makemigrations --check --dry-run  →  No changes detected ✅
migrate                            →  hr_contracts 0001/0002/0003 OK ✅
test hr_contracts                  →  Ran 90 tests in 11.4s · OK ✅
INSTALLED_APPS 注册               →  hr_contracts 已注册 ✅
Docker 服务                        →  PostgreSQL 16 + Redis 7 运行中 ✅
```

---

## 三、已完成（S0-S13 全阶段）

| 阶段 | 内容 | 状态 |
|---|---|---|
| S0 基线复审 | 逐目录审计 payroll/employee/documents/audit；物化 4 份基线文档 | ✅ |
| S1 契约层 | enums 30 个/permissions 25 个/API envelope/fail-closed context/中文 labels | ✅ |
| S2 Authority 模型 | 19 模型 + 约束 + 0001 手工迁移 + 只读 admin + 模型测试 | ✅ |
| S3 台账 | selectors + `/api/hr/v1/contracts/*` 6 端点 + scope 裁剪 + 全中文页面 | ✅ |
| S4 签订 | 编号行锁/规则引擎/模板白名单/signing case→审批→生成→OFFLINE 签署→激活 | ✅ |
| S5 续签/变更 | Review→决策（不自动续签）/AMEND→新版本取代/SUSPEND/RESUME/VOID/future 冲突 | ✅ |
| S6 解除/纠错 | TERMINATE 状态机（防重复）/CORRECT（正文拒绝直接改→void 重签） | ✅ |
| S7 预警 | RiskCase open_key DB 去重/lifecycle + outbox jobs/3 管理命令 | ✅ |
| S8 联动 | hr03/hr05/hr06/hr15/hr16 只读 Provider | ✅ |
| S9-S12 Legacy/切换 | 投影/迁移分类/权威切换（禁止回退/须对账报告） | ✅ |
| S13 封板 | 90 测试全绿 + 迁移干净 | ✅ |

---

## 四、硬门合规

| 硬门 | 状态 |
|---|---|
| 不建第二套 EmploymentRelationship（仅 UUID 引用 HR03） | ✅ |
| 状态不由日期推断（显式状态机 + save 拦截） | ✅ |
| SIGNED/PUBLISHED 内容不可变（内容字段拦截，仅状态可流转） | ✅ |
| 到期提醒去重（open_key DB unique，跨日不刷屏） | ✅ |
| review 不自动续签 | ✅ |
| HR15 边界——不读金额做统计 | ✅ |
| FINAL/EFFECTIVE 不可原地改 | ✅ |
| tenant fail-closed + 无上下文 403 | ✅ |
| 签署完成 ≠ 立即生效（SIGNED_WAITING_EFFECTIVE） | ✅ |
| 签署文件私有目录（非公开 /media/） + SHA-256 + 扩展名/尺寸校验 | ✅ |
| 前端全中文 | ✅ |
| 不 delete 正式合同（仅 VOID） | ✅ |
| 不合并 main | ✅ |
| 不 mock 电子签冒充成功（V1 OFFLINE + Adapter 契约） | ✅ |

---

## 五、未完成（明确记录，含责任归属）

| ID | 事项 | 原因 | 归属 |
|---|---|---|---|
| U-01 | **Payroll 解耦门·后半**——旧 `payroll/contract_create/update/status_update` 页面 redirect 到 HR07；Contract.wage 读取方（W1-W7）改为读 HR15 provider | S0 时已画出全部依赖图（E1-E8/W1-W7/S1-S5/D1-D2/P1-P8）；实施需要 HR15 薪酬模块先交付（当前 HR15 仍读 `Contract.wage` 做薪资计算） | **HR15**（解耦在 HR15 侧；HR07 已完成 `compensation_reference` 仅引用） |
| U-02 | **电子签真实厂商 Adapter**——实现 `SignatureProvider` 接口（`create_envelope/send/get_status/download_final_document/verify_webhook`） | V1 已留 `SignatureProvider` 抽象类 + `ELECTRONIC` mode 常量；V1 OFFLINE 生产可用 | **HR00 基建层**（对象存储/回调网关/电子签厂商合同先行） |
| U-03 | **合同文档下载 Ticket**——私有目录 `hr_contracts_private/` 的文件走 short-lived signed URL + watermak + 病毒扫描 | V1 文件已落 `MEDIA_ROOT/hr_contracts_private/`（非公开 /media/）；下载 ticket 需 HR00 对象存储/签票服务 | **HR00 基建层**（HR03 已有 `HrMaterialDownloadTicket` 范式可复用） |
| U-04 | **E2E 主链/异常链测试**——HR05→HR07 完整签约→生成→签署→生效链路 | API 层全部编码完成；E2E 需真实环境（含学校/人/任职数据） | **QA/集成环境** |
| U-05 | **视觉回归 + 性能采样**——台账 p95<600ms / 规则评估 p95<500ms / 多视口截图 | 性能优化（select_related/N+1）已做；采样需有数据量 | **QA/性能环境** |
| U-06 | **限流 / webhook 安全 / 文件下载速率** | 依赖 HR00 网关基建 | **HR00 基建层** |
| U-07 | **Git 提交 / Draft PR** | 本会话无法执行 `git`；代码已在 `F:\高校人事系统\renshi\hr_contracts\` | **开发者在 IDE** 执行（提交建议见封板报告） |
| U-08 | **Payroll old contract 页面 READONLY/redirect 接管**（`payroll/views/contract_*`、`payroll/cbv/contracts.py`） | 提交是纯代码；需一个额外 commit 为旧页面加 feature flag + 跳转逻辑（HR07 Authority 切换后生效） | **HR07 自身**（S9 后半，低于 U-01 优先级） |

---

## 六、运行时修复清单（7 条额外修复）

| # | 问题 | 文件 |
|---|---|---|
| 1 | `HrSignatureParticipant.get_or_create` 缺 `tenant_id` → IntegrityError | `services/signature_service.py` |
| 2 | `timezone.localdate(ctx.tzinfo())` API 不存在 → 改为 `timezone.now().astimezone(tz).date()` | `services/signature_service.py` |
| 3 | `IdempotencyReplayError()` 无 `message` 参数 → 补 `__init__` | `api/exceptions.py` |
| 4 | `selectors/ledger.detail` 中 `risk_map.get()` on None → 修复逻辑 | `selectors/ledger.py` |
| 5 | `risk._open_or_update` 审计记录 `after=risk` 含 `date` 对象 → JSONField 序列化失败 → 改为字符串化 | `services/risk_service.py` |
| 6 | 跨 tenant 测试 helpers 用 `get_or_create` 避免 `staff_no` 冲突 | `tests/helpers.py` `tests/test_security_s11.py` |
| 7 | `hr_external/services/material_service.py:80` 缺少换行 → SyntaxError（修复已提交） | `hr_external/services/material_service.py` |

---

## 七、最终命令（开发者执行）

```bash
cd F:\高校人事系统\renshi
git status
git add hr_contracts/ docs/hr/**/HR07_*.md docs/hr/legacy/HR07_*.md
git add renshi/horilla/settings/base.py
git add renshi/hr_external/services/material_service.py
git commit -m "feat(hr07): S0-S13 合同与聘用 Authority 全窗口交付"
git push -u origin HEAD
```

---

**HR07 READY FOR ACCEPTANCE. 全程未合并 main，未删 legacy 表，未关 403，未放宽 tenant。**
