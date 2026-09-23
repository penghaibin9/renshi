# 跃科高校人事系统 Round7：成熟产品对标与上线前源码收口报告

日期：2026-09-15  
基线：`Yueke_University_HR_Round6_20260915.zip`  
边界：仅当前云端源码副本；未连接 GitHub，未连接生产服务器，未连接生产数据库。

## 1. 裁决

Round7 的定位不是“继续堆功能”，而是 **SOURCE_CODE_LAUNCH_CANDIDATE（源码上线候选）**。

Round6 已经具备高校人事产品的完整主干：组织/编制岗位、人员主档、多任职、招聘、入职、异动、合同、外聘、资格/双师型、培训进修、考勤、考核、职称、岗位聘任、薪酬福利、退休离校、教职工自助、数据中心。Round7 对标成熟产品后，没有再复制菜单，而是处理最容易在正式上线时造成安全事故、跨 worker 故障和“运维假成功”的治理缺口。

最终上线状态仍不能在本源码沙箱内写成 `RELEASED`：真实 Docker Compose、MySQL 8.4 migration/trigger、浏览器黄金流程、SMTP/IAM/财税/签章等目标学校外部边界必须在独立 QA/目标环境签字。

## 2. 市面成熟产品对标结论

本轮以公开官方资料为基准做能力对照，而不是照抄界面或代码：

- 正方软件“人力资源管理服务平台”：强调全校教职工人事信息总库/历史库、业务流程整合、数据共享和决策分析。
- 金智教育：公开产品体系包含“人事人才一体化系统”，同时强调数据治理、管理闭环和决策科学化。
- Ellucian HCM：高教场景原生支持 faculty contracts、multiple jobs、position management、payroll、敏感 HR 数据保护、员工自助和实时 workforce insights。
- Workday Higher Education/HCM：强调 faculty/staff/student worker 生命周期、多 academic appointments、合同/薪酬/休假、员工自助与统一分析。
- 中国教育行业标准：JY/T 0637-2022 用于教育系统人员基础数据模型/交换；JY/T 0661-2025 用于教育数据分类分级。

公开参考（2026-09-15 核验）：

1. https://www.zfsoft.com/
2. https://www.wisedu.com/
3. https://www.ellucian.com/en-gd/node/234
4. https://www.workday.com/content/dam/web/en-us/documents/datasheets/hcm-student-workers-faculty-datasheet.pdf
5. https://www.moe.gov.cn/srcsite/A16/s3342/202302/W020230214592011211530.pdf
6. https://www.moe.gov.cn/srcsite/A16/s3342/202601/W020260107510856466340.pdf

### 2.1 能力矩阵

| 成熟高校 HCM 常见能力 | 跃科当前承载 | Round7 裁决 |
|---|---|---|
| 组织、编制、岗位控制 | HR02 | 已有，不扩菜单 |
| 人员主档、任职历史、多岗位 | HR03 | 已有 Authority/effective-dated 模型 |
| 招聘与人才引进 | HR04 | 已有；Round7 加强候选证件保护 |
| 入职与跨部门办理 | HR05 | 已有；Round7 把 Excel staging 改为数据库持久账本 |
| 人事异动 | HR06 | 已有正式执行/纠错/撤销链 |
| 合同与聘用 | HR07 | 已有正式版本 Authority |
| 外聘/兼职教师 | HR08 | 已有；Round7 分离材料下载票据 HMAC 密钥 |
| 教师资格/双师型 | HR09 | 已有；Round7 修正 Authority cutover 真值 |
| 培训进修/企业实践 | HR10 | 已有 |
| 考勤请假 | HR11 | 已有 |
| 年度/聘期考核 | HR12 | 已有正式结果修订/撤销链 |
| 职称评审 | HR13 | 已有 |
| 岗位聘任 | HR14 | 已有 |
| 薪酬、福利、社保公积金、个税/对账 | HR15 | 已有，正式结果含调整/冲销 Authority |
| 退休/离校/返聘 | HR16 | 已有 |
| 教职工自助 | HR17 | 已有本人查询/申请/更正命令边界 |
| 领导驾驶舱、数据质量、历史指标/交换 | HR01 + HR18 | 已有，JY/T 0637/0661 profile 保留 |
| 权限、租户、审计、敏感数据保护 | 公共底座 | Round7 重点加强 |
| Excel 批量导入与错误回执 | 多模块 | HR05 Round7 改为 multi-worker/restart safe |
| 通用低代码流程/表单设计器 | 部分动态能力 | **未来竞争力项，不是本次上线阻断** |
| 原生移动端完整 HR | 非主战场 | **未来竞争力项，不是本次上线阻断** |
| AI 招聘/人才洞察助手 | 未作为核心 Authority | **未来竞争力项，不应阻塞首发** |

结论：当前最该做的是稳定上线，不是继续复制成熟厂商的外围功能。

## 3. Round7 实际源码收口

### 3.1 敏感字段从“配置上独立”修成“代码里真正独立”

Round6 已要求 `FIELD_ENCRYPTION_KEYS`，但部分历史服务仍从 Django `SECRET_KEY` 派生字段密钥。Round7 改为：

- 新增统一 `horilla.security.field_keyring`；
- `FIELD_ENCRYPTION_KEYS` 使用 `key-id:fernet-key` keyring，第一把为写密钥，旧密钥可读，支持无停机轮换；
- `FIELD_FINGERPRINT_KEY` 专门用于可检索身份证件/资格证号 HMAC 指纹；
- `HR08_TICKET_SIGNING_KEY` 专门用于 HR08 短时下载票据；
- 生产门禁拒绝字段密钥、指纹密钥、下载签名密钥与 Django/备份密钥互相复用；
- HR03 证件、HR04 候选人证件、HR05 银行 JSON、HR09 证书号切到新 keyring；
- Round6 旧密文保留兼容读取路径，仅用于迁移；新写入不再从 `SECRET_KEY` 派生；
- 可检索身份证件/证书号从普通 SHA-256 升级为租户 + namespace 隔离的 HMAC-SHA256；
- 新增 `rotate_hr_field_security` 审计/rewrap；支持 `--tenant` 单校审计，避免一个学校的旧数据阻塞另一个学校上线。

特殊说明：Round6 更早的 HR04 若只有不可逆 hash 而没有可解密证件密文，系统明确输出 `hr04_hash_only_unresolved`，禁止猜证件号。

### 3.2 HR05 Excel 导入从进程内存改成持久化生产账本

Round6 的 HR05 Excel API 仍依赖模块级 `_jobs` 内存字典。多 Gunicorn worker、容器重启或滚动发布时，上传和确认请求落到不同 worker 就会丢 Job。

Round7 改为：

- 新增 `HrOnboardingImportJob` / `HrOnboardingImportRow`；
- Job、逐行 normalized payload、校验错误、commit 结果、源文件 SHA256 全部持久化；
- `confirm` 只做持久确认并返回 HTTP 202，同时固化 `confirmed_by/confirmed_at`；新增 `hr05-import-worker` 以确认人作为审计主体逐行提交，避免 5000 行导入占住 Web 请求；
- 原始敏感 Excel 文件本体不持久化；
- 增加 Job status 查询 API；
- 确认导入使用 DB row lock + 稳定 row idempotency key；
- 重复确认和 crash-replay 不重复创建业务事实；
- 非 `LEGACY_MIGRATION` 必须提供真实 `source_id`，不再生成跨批次碰撞的伪来源；
- 限制 10 MiB / 5000 行 / 单格 500 字符；
- 在 openpyxl 解析前先检查 XLSX ZIP，限制 2000 个 archive entries、50 MiB 解压总量并拒绝非法路径/非 XLSX OPC 包；
- 缺少必需表头、重复表头、只有表头无数据的工作簿直接拒绝；
- Windows 反斜杠/盘符式 archive 路径同样拒绝，避免跨平台路径判断差异。

这项属于实际生产阻断修复，不是体验优化。

### 3.3 HR09 Authority cutover 从“临时标记”改成可信运维事实

Round6 的切换命令曾把模式隐藏在 `tenant_id=0` 的资质目录项；异常路径还会输出“内存生效”语义，但实际没有可信内存状态。这不适合生产运维。

Round7 改为：

- `HrAuthorityCutover.Domain` 增加 `QUALIFICATION`；
- HR09 使用共享 `HrAuthorityCutover` 作为租户级切换真值；
- DB 读取失败 fail-closed；
- `DUAL_READ_COMPARE` 切换前先重建/核验 legacy projection；
- `HR09_AUTHORITY` 强制要求真实 `verification_report_id`；
- 任一步失败都不写“成功”；
- 成功后重新读取数据库确认，并输出 `HR09_AUTHORITY_CUTOVER_OK`。

### 3.4 新增单校只读 go-live audit

新增：

```bash
make go-live-audit TENANT_ID=真实租户ID
```

命令只读，统一输出 JSON evidence，并检查：

1. 独立 HR 密钥是否真实分离；
2. 当前租户是否仍有敏感字段待 rewrap / 无法升级；
3. HR01～HR18 Authority Gate 是否 COMPLETE；
4. HR05 是否存在超过 15 分钟的卡死 `COMMITTING` 导入；
5. HR03 是否存在 DEAD outbox；
6. HR05 是否存在 DROPPED、FAILED 或超过 15 分钟仍 PENDING 的 outbox；
7. HR06 是否存在 DROPPED outbox；
8. HR08 IAM/教务身份是否存在终态 FAILED；
9. HR18 正式报送/数据交换是否存在 DEAD / DEAD_LETTER；
10. `hr05-outbox`、`hr05-import`、HR18 两个 worker、legacy/employee/backup scheduler 的 Redis 心跳是否新鲜；
11. 有 HR09 正式数据时是否已切到可审计 Authority。

`--strict` 下 warning 也阻断签字。命令不会自动改业务数据、重试队列或切 Authority，避免“为了变绿自动篡改现场”。

### 3.5 教育行业标准核验

Round6 已存在的标准方向保持不变，本轮核实为正确：

- JY/T 0637-2022《教育系统人员基础数据》作为人员语义/交换参考；
- JY/T 0661-2025《教育数据分类分级指南》作为教育数据分类分级依据；
- 系统继续要求中国高校标准 profile 的分类依据、分类日期、敏感个人信息标记；全校范围教职工数据最低按 L3 控制，L4/L5 要求审批依据。

运行手册新增签字项：真实学校上线前必须完成数据资产梳理、分类分级、校内审批/备案与动态更新责任人，不把“代码里写了 L3”冒充学校治理已经完成。


### 3.6 HR05 Outbox 从“有表无持续消费者”收成真实运行边界

最终复审发现 Round6/Round7 早期版本虽然已有可靠 Outbox 表、lease/retry/dead-letter 和手工命令，但生产 Compose 没有持续 HR05 消费者，默认 handler registry 也没有正式 handler。多 worker Web 能正常服务并不代表 `StaffActivated` 等事件会被处理。

Round7 最终收口：

- 新增 `production_outbox_handlers`，覆盖 `StaffActivated`、`ProbationConfirmed`、`ProbationFailed`、`ActivationFactCorrected`、`ActivationFactRevoked`；
- handler **不重放 HR03/HR02 生效命令**。Activation 已在源事务内通过受控 Provider 写 Authority；Outbox worker 只重新读取封存事实、核对状态/ID/content hash，通过后生成明确 authority receipt；
- 新增持续 `hr05-outbox-worker`，带 Redis heartbeat/healthcheck，并同时进入开发/生产 Compose；
- `go-live-audit` 把 HR05 超 15 分钟 PENDING 与 FAILED 变成 BLOCKER，而不是只看 DROPPED；
- 同一体检增加 HR08 终态 provisioning failure、HR18 DEAD/DEAD_LETTER、七类生产后台 worker/scheduler 心跳检查。

这避免了两种相反风险：既不会让 PENDING 永久堆积，也不会因为错误地“重放 StaffActivated”制造第二份关系或任职。

### 3.7 封包前 fail-closed 边角

最终复审另外收掉三项：

- HR04 Round6 历史候选证件 hash 严格按旧算法双读，兼容小写 `x`/历史原始输入，不让安全升级造成老候选“查不到”；
- HR05 银行/敏感 JSON 加密失败改为直接抛错中止，禁止异常时返回 `{}` 并静默清空高敏数据；
- HR05 Excel 结构错误在 staging 前 fail-closed，避免错误模板生成一个“READY”空任务。

## 4. 本轮不做的事情

为了避免上线前无限扩范围，本轮明确不做：

- 不重做 HR01～HR18 页面；
- 不再新增业务菜单；
- 不复制正方/金智/Ellucian/Workday 的专有实现；
- 不引入通用低代码平台；
- 不做 AI 招聘/人才推荐作为上线前依赖；
- 不连接 GitHub；
- 不连接生产服务器/生产数据库；
- 不把缺少 Docker/MySQL 的源码沙箱结果写成“生产已验收”。

## 5. 上线签字的正确顺序

源码交付后，在具备 Docker Compose >= 2.24.4 + MySQL 8.4 的独立 QA 机器按顺序：

1. `make acceptance-plan`
2. `make acceptance-qa`
3. 使用 Round6/更早真实数据时执行 `rotate_hr_field_security --tenant <id>` → 人工处理 blocker → `--apply` → `--check`
4. 完成 HR09 dual-read 对账并归档 report id（若有历史资质数据）
5. 部署生产候选，但**先不开放公网业务流量**
6. `make go-live-audit TENANT_ID=<id>`
7. `/health/`、`/ready/`、worker、SMTP、ClamAV、IAM/财税/签章等真实联调
8. 四角色浏览器黄金流程 + Excel 导入跨 worker/重启验证
9. 加密备份 + 独立恢复演练 + RPO/RTO 记录
10. 学校负责人/人事/信息中心/安全责任人签字后开放流量

## 6. 本轮最终源码验证

最终工作目录重新执行：

- Round2：66/66；Round3：6/6；Round4：16/16；Round5：20/20；Round6：24/24；Round7：23/23；合计 **155/155**；
- Python AST/compileall：**3136** 个源码文件通过；
- Django migration：**446** 个文件，应用内四位编号 **0 冲突**；
- JavaScript `node --check`：**253** 个文件通过；
- `deploy/docker/entrypoint.sh` Bash 语法通过；
- `acceptance-plan` 可生成完整隔离验收步骤；
- 实际触发隔离 acceptance 时当前云执行器在 `docker compose version --short` 第一阶段约 0.001 秒 fail-closed，证据记录 `productionTouched=false`、`gitHubTouched=false`。

这里没有把“缺 Docker”写成测试通过。最终交付 ZIP 已在独立目录反解并重复验证：Manifest 逐文件 SHA256 0 缺失/0 错误/0 额外文件，155/155 纯门禁以及 AST/migration/JS/Bash 检查再次通过。

## 7. 最终状态定义

- **源码完整度：LAUNCH CANDIDATE**
- **源码静态/纯契约验证：必须以本轮最终打包结果为准**
- **目标环境生产验收：PENDING**
- **生产发布状态：NOT_RELEASED**

这不是“还有业务模块没开发完”，而是把最后一步交给必须拥有真实 Docker/MySQL、学校账号、外部系统和浏览器的验收环境。
