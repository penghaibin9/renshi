# 高校人事系统 Round11：学校数据开放移交与采购级可迁移验收收口报告

日期：2026-09-17  
唯一源码基线：`Yueke_University_HR_Round10_20260916.zip`  
参考材料：用户提供的 9 页《一站式非学历教育智慧前台建设项目采购清单》  
施工边界：云端源码副本；未连接 GitHub、生产服务器、生产数据库或真实学校接口。

## 1. 为什么 Round11 做“学校移交”，而不是继续加菜单

采购参考的第 13～14 项把学校项目的交付边界写得很清楚：项目最终要交付可独立部署的软件版本、数据库脚本、部署配置、接口文档、数据字典、测试/用户/试运行/整改材料；学校业务数据、数据字典、字段映射、数据库结构、接口文档和专属配置归采购人所有，合同终止或更换供应商时还应提供完整、结构化、可复用的数据与资料移交，不能依赖专有格式、封闭接口或只有原供应商才能解开的数据形态。

现有系统已经有生产 AES 加密灾备链，但“灾备”和“采购人退出时的开放移交”目标不同：

- 灾备首先追求机密性、自动化轮转和同系统恢复；
- 学校移交首先追求开放格式、供应商退出后仍可解释/恢复、资料归属清晰、可核验。

因此 Round11 没有删除或弱化现有灾备，而是新增独立的 portability/handover authority path。

## 2. 新增开放格式学校移交包

新增命令：

- `create_school_handover_package`
- `verify_school_handover_package`
- `restore_school_handover_package`

生成移交包前必须明确：

- recipient；
- purpose；
- operator；
- 固定敏感数据导出确认词。

包存储和审计回执目录必须独立于 Web/Static/Media/frontend，包与 sidecar checksum 使用受限权限。

### 2.1 包内开放格式

至少包括：

- `database.sql`：标准 MySQL logical dump；
- `media.tar.gz`：标准 POSIX tar.gz；
- `schema_dictionary.csv/json`：字段级数据库字典；
- `table_row_counts.csv/json`：绑定 `database.sql` 实际 INSERT 的精确行数证据；
- `migration_state.json`：Django migrations；
- `api_route_inventory.csv`：当前 URL surface；
- `configuration_catalog.csv/json`：规则/配置/策略/周期/映射类表索引和行数；
- `interface_mapping_catalog.json`：HR18 非密钥字段映射；
- `runtime_configuration.json`：不含密码/密钥值的环境说明；
- `secret_handover_requirements.json`：需要单独交接或重签发的密钥类别与 Key ID；
- `delivery_docs/`：部署、兼容性、权限、Authority、Provider、对账文档；
- `README-HANDOVER.txt`；
- `manifest.json`：除自身外每个 artifact 的 byte size + SHA-256。

外层另生成同名 `.sha256` 文件。校验和恢复命令在解包前必须先核对 detached SHA。

## 3. 为什么精确数据行数必须绑定 database.sql

仅检查“恢复后有多少张表”不够。

一种真实失败模式是：SQL 导入中途丢失部分 INSERT，但 DDL 都执行了。此时：

- 表数量相同；
- migration 记录甚至可能存在；
- 页面却已经丢业务数据。

Round11 因此增加精确 row-count evidence。

重要实现细节：行数**不在 mysqldump 完成后重新查询实时生产库**。因为导出期间若仍有写入，实时 `COUNT(*)` 会与 `--single-transaction` 捕获的 dump snapshot 发生时点漂移。

当前 `dump_mysql_db` 使用 `--skip-extended-insert`，每个导出数据行对应一条 INSERT。Round11 直接统计 `database.sql` 中每个表的 INSERT 行数，生成 CSV/JSON；恢复后对这些表逐一执行 `COUNT(*)`，任何 mismatch 都拒绝验收。同时比对总业务行数、schema table count 和 migration count。

这使“完整性判断”绑定于**实际交付出去的 SQL**，而不是导出之后继续变化的生产库。

## 4. 数据包完整性和归档安全

`handover.py` 提供统一安全原语：

- 外层 archive 禁止绝对路径；
- 禁止 `..` 路径穿越；
- 禁止 symlink/hardlink/device members；
- 解压逐成员确认目标仍在 destination 下；
- 临时文件 0600 + atomic replace；
- Manifest 缺文件、大小变化、SHA 不一致直接失败；
- Manifest 以外出现额外文件也失败；
- `media.tar.gz` 做二次结构检查；
- detached `.sha256` 缺失、格式错误、文件名不匹配或 digest 不一致均失败。

因此“有人拿到一个 tar.gz 能打开”不等于验证通过。

## 5. 密钥：既不能泄露，也不能形成供应商锁定

一个容易走向两个极端的问题是字段级密文：

1. 把字段加密密钥直接塞进移交包 —— 泄密；
2. 完全不给学校解释/解密所需密钥 —— 形成供应商锁定。

Round11 的合同是：

- `FIELD_ENCRYPTION_KEYS`：包内只列 configured Key IDs，**密钥值通过学校控制的独立安全通道单独移交**；
- `FIELD_FINGERPRINT_KEY`：单独移交或执行经过批准的受控 reindex；
- `SECRET_KEY`：目标环境重签发；
- 临时票据/签名 key：重签发；
- SSO/SMTP/数据中台/省级平台等第三方凭据：由责任方轮换/重签发；
- 生产灾备加密 key：只有历史加密灾备也列入合同移交时才单独处理。

`runtime_configuration.json` 和 `secret_handover_requirements.json` 不允许保存真实 secret value。

## 6. 恢复只允许到隔离空库

恢复命令具有以下硬约束：

- 目标库名仅允许安全字符；
- 目标库不能等于当前 configured production DB；
- `--confirm-target` 必须与目标名完全一致；
- 必须显式提供 `RESTORE_TO_EMPTY_DATABASE_ONLY`；
- 目标库必须已经存在且为空；
- RESTORE DB password 通过 `MYSQL_PWD` child environment 传递，不进入 argv；
- media 先完整验证/预解包，再开始 MySQL mutation；
- SQL 导入后再做表数、migration 数、逐表精确 row count 和总 rows 校验；
- media 仅在 DB postcheck 成功后 atomic swap 到目标目录；
- 成功后追加 RESTORED receipt。

MySQL DDL 不能保证整库事务回滚，所以 runbook 明确：中途失败不能在半恢复库上继续赌重试，必须删除隔离目标库后重新创建空库。

## 7. 审计证据不覆盖历史

新增 JSONL append-only receipt：

- `CREATED`
- `VERIFIED`
- `RESTORED`

使用 `O_APPEND|O_CREAT|O_WRONLY`，不会为了“最新状态好看”重写原导出/校验历史。

## 8. 生产 Compose 与操作手册

新增配置：

- `SCHOOL_HANDOVER_ROOT`
- `SCHOOL_HANDOVER_RECEIPT_ROOT`
- `HANDOVER_STORAGE_PATH`
- `HANDOVER_AUDIT_STORAGE_PATH`

生产 Compose 在 backup-scheduler 挂载：

- `/app/handover`
- `/app/handover-audit`

`docs/PRODUCTION_RUNBOOK.md` 已增加学校移交章节；`docs/qa/SCHOOL_HANDOVER_ACCEPTANCE_CHECKLIST.md` 冻结 A～G 七段验收。

正式移交仍必须有**维护/写入冻结窗口**。数据库 single-transaction 与媒体文件系统不是同一个分布式事务，代码不能伪造“外部流量确实已经冻结”的证据。

## 9. 已把 Round11 接进生产形态 acceptance harness

`run_hr_acceptance_gate.py` 不再只验原加密灾备。

在具备 Docker/MySQL/Django 的 QA 环境，它会：

1. 建独立 acceptance Compose project 和随机 secrets；
2. release/migrate/check/test；
3. 创建、校验原生产加密灾备；
4. 恢复到 `renshi_restore_test`；
5. 创建开放 school handover；
6. 比较 create/verify 返回的 SHA-256；
7. 恢复到第二个独立 `renshi_handover_restore_test`；
8. 由 restore command 完成 exact row counts postcheck；
9. 对恢复库执行 `migrate --check`；
10. 比较原库与 handover restore DB 的 schema table counts；
11. 启动 Web 并验证 `/ready/` HTTP 200；
12. 默认销毁本次 acceptance project/volumes。

因此以后不能只跑一个静态脚本就宣布“迁移能力通过”。

## 10. 当前真实验证结果

本云端执行器已真实执行：

- HR10 import static：20/20 PASS；
- HR10 canonical staff identity static：53/53 PASS；
- HR18 procurement sync static：24/24 PASS；
- Round11 school handover portability static：33/33 PASS；
- Round11 pure unittest：11/11 PASS；
- Round2～Round11 pure unittest 总计：180/180 PASS。

最终封包前的全仓静态解析已经执行：

- Python AST：3,154 个 `.py` 文件，0 错误；
- JavaScript `node --check`：253 个 `.js` 文件，0 错误；
- acceptance `--plan`：成功生成包含开放移交 create/verify/restore 的隔离验收计划。

动态执行已实际尝试：

```text
python manage.py check --deploy
```

当前执行器返回：

```text
ModuleNotFoundError: No module named 'django'
```

同时当前执行器不存在 `docker` 命令，所以真实 Compose/MySQL handover drill **没有执行**。状态必须保持：

**SOURCE_CODE_CANDIDATE / NOT_RELEASED**

## 11. 正式放行还缺什么

在有完整依赖的隔离 QA 环境执行：

```bash
python scripts/run_hr_acceptance_gate.py --project yueke_hr_acceptance_round11
```

并完成 `docs/qa/SCHOOL_HANDOVER_ACCEPTANCE_CHECKLIST.md`：

- 导出前写冻结；
- 包 + SHA sidecar；
- field key 独立安全通道；
- 空库恢复；
- HR01～HR18 代表性事实抽样；
- 附件读取；
- 敏感字段解密/fail-closed；
- `/health/` / `/ready/`；
- 接收/校验/恢复/验收签字。

只有以上动态证据完成，Round11 才能从 NOT_RELEASED 转为 release candidate。
