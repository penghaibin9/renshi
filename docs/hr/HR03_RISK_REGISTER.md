# HR03 RISK REGISTER（S0 基线复审 · 风险登记册）

> 依据：《03_HR03_教职工主档_施工总册_终极版》#55 事故级负向验收 + 真实仓库核对 + HR01/HR02 风险习惯。
> 严重度：P0=封板阻断；P1=必须治理；P2=观察项。
> 状态：OPEN / MITIGATING / WATCH / RESOLVED

---

## 1. 数据正确性风险

| ID | 风险 | 真实代码证据 | 影响 | 缓解策略 | 状态 |
|---|---|---|---|---|---|
| R-D-01 | 调岗/调学院直接 UPDATE 当前字段，历史丢失 | `employee_work_info_view_update`/`employee_update_work_info` 直接 save 受管字段；无 effective-dated | as_of 历史错误；HR01 历史指标失真 | S3 权威 assignment 段；EffectiveDatedQueryService 唯一 as-of 入口 | OPEN |
| R-D-02 | `is_active` 被当作人事状态真值 | `HorillaCompanyManager.all()` 默认 is_active 过滤；`employee_filter_view` is_active 筛选；`workforce.py` 在岗口径 | 离职/退休/停职混淆；归档回弹 | S3 状态由关系/任职段推导；S11 投影单向；legacy 写入口关闭 | OPEN |
| R-D-03 | 返聘/再次入职创建第二个"人" | 无 Person 层；badge/email 唯一 | 一人两档 | S2 Person+Staff 分离；rehire 关联已有 Person（不变量 #20） | OPEN |
| R-D-04 | 一个自然人兼任多岗仍单字段 | `EmployeeWorkInformation` OneToOne + 单 department/job_position | 兼岗丢失 | S3 assignment_type=PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT | OPEN |
| R-D-05 | 同一人跨校重复 Person | email 全局唯一逼出"假唯一"；无跨校共享政策 | 同人异档 | V1 tenant-private Person + LIKELY_MATCH 人工去重；禁止自动跨校合并 | OPEN |
| R-D-06 | 历史日期页面显示当前学院 | 无 as-of 解析；profile 读当前 work_info | 事故级负向 #55 第 10 项 | S5/S6 as-of 强制只读 + 组织名 HR02 as-of 解析 | OPEN |
| R-D-07 | 教育/经历/证件塞 JSON | `Employee.additional_info`、`qualification` 单字符串 | 不可治理黑洞 | 结构化独立模型；JSON 不作为正式事实容器 | OPEN |

## 2. 安全与隐私风险

| ID | 风险 | 真实代码证据 | 影响 | 缓解策略 | 状态 |
|---|---|---|---|---|---|
| R-S-01 | 高敏字段进列表/首屏 | `Employee.phone/email/dob` 直接列表显示；`get_employees_birthday` 读 dob | 隐私泄漏 | 四级字段策略；高敏不入列表 API；服务端裁剪 | OPEN |
| R-S-02 | 身份证明文/无指纹去重 | 无身份证模型 | 明文泄露、弱去重 | HrPersonIdentityDocument ciphertext+fingerprint+masked；明文查看独立权限+purpose+审计 | OPEN |
| R-S-03 | 材料 `/media/` 裸 URL 长期暴露 | `Document.document.url`；`view_file` 直接响应 | 猜 URL 越权下载 | S8 受控存储 + download-ticket 短时效一次性 | OPEN |
| R-S-04 | 跨学校越权（staffId 猜测） | legacy `employee_view` 按 id 取，靠 CompanyManager 过滤 | A 校看 B 校 | 权威表 tenant_id + scope 校验在 service 层，404/403 不泄漏存在性 | OPEN |
| R-S-05 | email 全局唯一阻断多关系 | `Employee.email unique=True`；EmployeeForm 全库查重 | 一人多关系无法表达 | PersonContact 独立；legacy email 唯一逐步解除（S11） | OPEN |
| R-S-06 | 审计日志含 PII | `HorillaAuditLog` 宽 try/except，历史记录含字段全文 | 身份证/银行卡进日志 | HrStaffAuditEvent 掩码快照；日志防泄漏清单（§28.3） | OPEN |
| R-S-07 | 前端拿到明文再遮罩 | 现状前端直接渲染 | 掩码可绕过 | 服务端裁剪；HrSensitiveValue reveal 走后端 endpoint+审计+60s 遮罩 | OPEN |

## 3. 架构与依赖风险

| ID | 风险 | 证据/依据 | 影响 | 缓解策略 | 状态 |
|---|---|---|---|---|---|
| R-A-01 | HR02 稳定 ID 未就绪 | **S0 复核更新**：`hr_structure` 已注册、已有迁移与 as-of 查询，代码层就绪 | 需在数据未映射时兜底 | 权威位 FK HR02 + `legacy_*` 映射列；未映射时 LEGACY_CURRENT_SNAPSHOT 只读预览；S11 对账回填 | MITIGATING |
| R-A-02 | 把 legacy Department/JobPosition 固化 FK | HR02_LegacyDataMapping 明确 COMPAT_ONLY | 历史迁移后难替换 | HR03 权威 FK 直指 hr_structure（HrOrganization/HrPosition）；legacy 仅经 HrLegacyObjectLink 映射列 | MITIGATING |
| R-A-03 | A0 tenant 过滤被 `.entire()`/管理命令绕过 | `HorillaCompanyManager.entire()` 存在；脚本直接 all() | 跨校污染 | 权威表自带 tenant_id + FK 同 tenant 校验；`system_scope(reason)` 唯一跨租户通道 | OPEN |
| R-A-04 | 同步逐行 Excel 导入留半成功 | `work_info_import` bulk_create + 无 staging | 半成功人员 | HrImportJob/Row/Issue 异步 staging；同人员多表原子 | OPEN |
| R-A-05 | `Employee.save()` 自动建 User 强耦合 | models.py 733-753 | 账号生命周期污染身份层 | authority save 禁建账号；HrAccountLink 解耦 | OPEN |
| R-A-06 | HR01 依赖 HR03 权威后无 fallback 契约 | 现状 provider 全 legacy | authority 故障偷读 legacy | AUTHORITY_ONLY + no-fallback contract test | OPEN |
| R-A-07 | btree_gist exclusion 依赖 | 未确认 PostgreSQL 扩展 | 区间重叠约束弱 | S0 能力预检；无扩展时事务锁+并发测试替代 | WATCH |

## 4. 验收/事故级负向风险（#55 映射）

| #55 负向场景 | 当前风险 | 防御落在阶段 |
|---|---|---|
| A 校改 B 校人员 | R-S-04/R-A-03 | S2/S3 service 层 tenant 校验 |
| 学院秘书猜 staffId 访问他院高敏档案 | R-S-01/R-S-04 | S2 scope + S8 材料票据 |
| 双并发 PRIMARY | G-H-11 | S3 条件唯一+事务锁+并发测试 |
| 过期 version 覆盖新数据 | G-H-11 | S3 version+409 |
| 更正直接改 BUSINESS_PROCESS_ONLY | G-06-04 | S9 FieldGovernancePolicy |
| authority 不可用偷偷读 legacy | R-A-06 | S11 no-fallback contract |
| 材料裸 URL 越权 | R-S-03 | S8 受控存储+票据 |
| 普通 export 带出身份证 | G-01-06 | S4/S8 导出字段权限 |
| rehire 创建重复 Person | R-D-03 | S2/S3 不变量 #20 |
| 历史日期显示当前学院 | R-D-06 | S5/S6 as-of 只读 |

## 5. 组织/过程风险

| ID | 风险 | 影响 | 缓解策略 | 状态 |
|---|---|---|---|---|
| R-P-01 | 当前工作区非 git 仓库（`F:\高校人事系统` 未检测到 `.git`） | 无法每阶段提交/开 Draft PR | S1 开始前确认仓库位置；若确实无仓库，交付物以文件落盘并由用户侧提交 | WATCH |
| R-P-02 | 上游测试欠账与新增回归混淆 | 假全绿 | `employee/tests.py` 为空文件；新测试独立标记 | WATCH |
| R-P-03 | 阶段越界（HR13/HR14 评审过程、HR02 重写、HR04 当作 Person） | 越界污染 | 本窗口硬边界：HR03 只接收生效事实；不反向改评审记录 | WATCH |
| R-P-04 | 加密方案不可运维（KMS/密钥轮换/备份恢复未定） | 数据无法恢复 | S2 先按"受控列+严格权限+日志防护"，应用层加密待威胁模型评审（总册 §49.6） | WATCH |

---

## 汇总
- P0 阻断：R-S-03（裸 URL）、R-S-01/02（高敏下发）、R-D-01/02（历史与状态）、R-S-04（跨校越权）、R-A-01（HR02 门）
- P1：其余 OPEN 项
- 无 RESOLVED 项（权威层尚未开工）
