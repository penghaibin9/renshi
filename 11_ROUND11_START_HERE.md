# 跃科高校人事系统：Round11 学校数据移交与采购级可迁移验收入口（2026-09-17）

唯一基线：`Yueke_University_HR_Round10_20260916.zip`  
采购参考：用户提供的 9 页《一站式非学历教育智慧前台建设项目采购清单》。

> 本轮只吸收采购文件中“部署上线、成果交付、数据归属、供应商退出/更换时可完整迁移”的验收要求，不改变 HR01～HR18 业务模块边界，也不把非学历教育业务照搬进人事系统。

## 一、本轮裁决

Round11 已把原有“加密灾备”与“学校开放格式移交”拆成两条独立链路：

- **灾备链**：继续使用原有 AES 加密生产备份，用于跃科系统自身灾难恢复；
- **学校移交链**：新增标准 MySQL SQL + tar.gz + CSV/JSON + 文档 + Manifest/SHA 的开放格式交付，用于项目最终验收、私有化迁移、合同终止或更换供应商。

当前状态：**SOURCE_CODE_CANDIDATE / NOT_RELEASED**。  
原因不是源码链路未实现，而是当前云端执行器没有 Django，也没有 Docker，无法在这里完成真实 MySQL/Compose 的“导出 → 校验 → 空库恢复 → Web ready”动态演练。

## 二、Round11 已完成

1. 新增 `create_school_handover_package`：显式接收方/用途/操作人/敏感导出确认后生成学校移交包。
2. 新增 `verify_school_handover_package`：先校验同名 `.sha256`，再检查外层 tar、Manifest、每个 artifact 的 bytes/SHA、未登记文件、路径穿越、链接/设备成员和内层 media tar。
3. 新增 `restore_school_handover_package`：只允许恢复到**与生产库不同的、已存在且为空的 MySQL 数据库**；密码仅通过环境变量传入。
4. 包内开放格式包括：
   - `database.sql`；
   - `media.tar.gz`；
   - 数据库字段字典 CSV/JSON；
   - `database.sql` 实际 INSERT 行数台账 CSV/JSON；
   - Django migration state；
   - API route inventory；
   - 规则/配置/字段映射目录；
   - 不含密钥值的运行配置；
   - 密钥/第三方凭据交接要求；
   - 部署/权限/数据库兼容/Authority/Provider/对账文档；
   - `manifest.json` 和 README。
5. `table_row_counts` **从 `database.sql` 本身统计**，而不是在 dump 完成后再查询仍可能变化的生产库；恢复后逐表 `COUNT(*)` 比对，防止“表都恢复了但业务行缺失”误判成功。
6. `FIELD_ENCRYPTION_KEYS` 不进移交包，只记录 Key ID 和“必须经学校控制的独立安全通道移交”的合同；`SECRET_KEY`、临时签名密钥、第三方账号在目标环境重签发/轮换。
7. 导出、验证、恢复均追加 JSONL 审计回执，不覆盖原历史。
8. Compose 增加独立 `/app/handover`、`/app/handover-audit` 持久卷；开放明文移交包不能混在 Web/Static/Media 路径。
9. `run_hr_acceptance_gate.py` 已接入真实 Round11 动态验收步骤：生成开放包、校验、恢复到第二个隔离数据库、`migrate --check`、比较 schema table counts，再启动 Web 验 `/ready/`。
10. 新增 `docs/qa/SCHOOL_HANDOVER_ACCEPTANCE_CHECKLIST.md`，冻结导出前、包内容、密钥、自动校验、隔离恢复、业务抽样和签字七段验收。

## 三、非常重要的运行边界

学校正式移交时必须安排经审批的**维护/写入冻结窗口**。

`mysqldump --single-transaction` 能保证事务型数据库快照的一致性，但数据库与媒体文件系统不是一个分布式事务。如果导出期间仍允许老师上传附件或修改业务配置，数据库引用与文件可能跨时点。本轮代码不会用一句“已导出”冒充已经证明外部流量被冻结；这仍是正式运维验收的前置条件。

## 四、关键文件

- `backend/horilla_backup/handover.py`
- `backend/horilla_backup/management/commands/create_school_handover_package.py`
- `backend/horilla_backup/management/commands/verify_school_handover_package.py`
- `backend/horilla_backup/management/commands/restore_school_handover_package.py`
- `backend/horilla/settings/base.py`
- `docker-compose.prod.yml`
- `.env.dist`
- `Makefile`
- `scripts/check_school_handover_contract.py`
- `scripts/run_hr_acceptance_gate.py`
- `tests/round11/test_school_handover_contract.py`
- `docs/qa/SCHOOL_HANDOVER_ACCEPTANCE_CHECKLIST.md`
- `docs/PRODUCTION_RUNBOOK.md`
- `docs/reports/HR_ROUND11_SCHOOL_HANDOVER_CLOSURE_2026-09-17.md`

## 五、本轮源码门禁

```bash
python scripts/check_hr10_import_contract.py
python scripts/check_hr10_staff_identity_contract.py
python scripts/check_hr18_procurement_sync_contract.py
python scripts/check_school_handover_contract.py
python -m unittest discover -s tests/round11 -p 'test_*.py' -v
python scripts/run_hr_acceptance_gate.py --plan --project yueke_hr_acceptance_round11
```

当前已实跑：

- HR10 import static：20/20 PASS；
- HR10 canonical staff identity：53/53 PASS；
- HR18 procurement sync：24/24 PASS；
- Round11 school handover portability：33/33 PASS；
- Round11 pure tests：11/11 PASS；
- Round2～Round11 pure tests 合计：180/180 PASS；
- 全仓 Python AST：3,154 文件，0 错误；
- JavaScript `node --check`：253 文件，0 错误。

## 六、正式 QA 环境必须补跑

优先运行项目已有的生产形态总门：

```bash
python scripts/run_hr_acceptance_gate.py \
  --project yueke_hr_acceptance_round11
```

它必须在 Docker Compose >= 2.24.4、有 MySQL 8.4 / Redis / ClamAV / Django 完整依赖的隔离 QA 环境中完成。Round11 新增步骤已经纳入该门：

1. 正常 release/migrate/check/test；
2. 原加密灾备创建/校验/恢复；
3. 开放学校移交包创建；
4. detached SHA + Manifest 校验；
5. 恢复到 `renshi_handover_restore_test` 空库；
6. 逐表精确数据行数检查；
7. `migrate --check` 与 schema counts；
8. Web `/ready/` HTTP 200；
9. 仅销毁本次 acceptance project/volumes。

正式放行前还要按 `docs/qa/SCHOOL_HANDOVER_ACCEPTANCE_CHECKLIST.md` 做业务抽样与签字。

## 七、下一轮边界

Round11 通过真实 MySQL/Compose 恢复演练前，**不要再把“可移交”写成 RELEASED**。后续采购清单可以继续用于 Round12 检查第 13 项剩余上线材料（初始化清单、试运行记录、问题整改清单）以及第 14 项管理员/经办人员培训交付，但不能用文档数量替代真实运行验证。
