# 学校数据与系统资料移交验收清单

适用场景：项目最终验收、合同终止、学校自建机房迁移、更换运维/供应商。

## A. 导出前

- [ ] 已明确学校接收部门、用途、操作人和审批/授权记录。
- [ ] `HANDOVER_STORAGE_PATH`、`HANDOVER_AUDIT_STORAGE_PATH` 不在 Web/静态/媒体公开目录内。
- [ ] 有足够磁盘空间，且导出目录权限仅授权运维人员可读写。
- [ ] 当前生产 MySQL 正常，迁移状态无漂移。
- [ ] 已进入经审批的维护/写入冻结窗口，避免数据库快照、附件与配置在导出过程中继续变化。

## B. 移交包内容

- [ ] `database.sql` 可由标准 MySQL 工具识别。
- [ ] `media.tar.gz` 可由标准 tar 工具识别。
- [ ] `schema_dictionary.csv/json` 存在且表/字段数量非零。
- [ ] `table_row_counts.csv/json` 存在，并且统计来源绑定到 `database.sql` 实际 INSERT 行。
- [ ] `migration_state.json` 存在。
- [ ] `api_route_inventory.csv` 存在。
- [ ] `configuration_catalog.csv/json` 存在。
- [ ] `interface_mapping_catalog.json` 存在。
- [ ] `runtime_configuration.json` 不含密码、Token、密钥值。
- [ ] `secret_handover_requirements.json` 只含密钥类别与 Key ID。
- [ ] `delivery_docs/` 包含部署/权限/数据库兼容/Authority/Provider/对账材料。
- [ ] `manifest.json` 覆盖除自身外全部文件并记录 bytes + SHA-256。
- [ ] 源代码按合同使用匹配版本的签字源码包单独交付。

## C. 密钥与第三方账号

- [ ] `FIELD_ENCRYPTION_KEYS` 已通过学校控制的独立安全通道交接。
- [ ] `FIELD_FINGERPRINT_KEY` 已交接，或新环境已有经批准的受控重建计划。
- [ ] `SECRET_KEY`、HR08 临时票据签名密钥在新环境重签发。
- [ ] SSO/数据中台/省级平台/SMTP/数据库账号由学校或接口责任方重签发/轮换。
- [ ] 任何密钥值均未写入移交包、源码包、工单、截图或普通日志。

## D. 自动校验

- [ ] `.tar.gz` 与同名 `.sha256` 一并收到，侧车 SHA-256 与包字节完全一致。
- [ ] `verify_school_handover_package` 返回 `SCHOOL_HANDOVER_VERIFIED`。
- [ ] 外层 tar 不含绝对路径、`..`、符号链接、硬链接或设备文件。
- [ ] 内层 media tar 结构校验通过。
- [ ] 无缺失文件、无未登记文件、无 size/SHA-256 差异。
- [ ] 导出/校验回执均已追加到独立 JSONL 审计文件。

## E. 隔离恢复

- [ ] 恢复目标库与生产库名称不同。
- [ ] 恢复目标库预先创建且为空。
- [ ] `--confirm-target` 与目标库完全一致。
- [ ] `--confirm-restore-policy RESTORE_TO_EMPTY_DATABASE_ONLY` 已显式提供。
- [ ] RESTORE_DATABASE_PASSWORD 只通过环境变量传入，不进入命令行参数。
- [ ] media 目标目录不存在或为空。
- [ ] media tar 在 MySQL 导入前已完整预校验。
- [ ] 恢复后表数量与导出 manifest 一致。
- [ ] 恢复后 `django_migrations` 数量与导出 manifest 一致。
- [ ] 恢复后逐表精确行数与 `table_row_counts.json` 一致；总业务行数一致。

## F. 业务抽样

- [ ] 组织、岗位、教职工主档、任职关系可查询。
- [ ] 招聘/入职、异动、合同、考勤请假、资质、培训实践、考核、薪酬、离退至少各抽样 3 条。
- [ ] 已归档/封存事实的历史快照与版本链存在。
- [ ] 附件可读取，权限仍按角色/组织生效。
- [ ] 规则版本、考核周期、字段映射、接口目标配置可读取。
- [ ] 使用恢复库启动隔离 Web，`/health/`、`/ready/` 正常。
- [ ] 至少一个经授权敏感字段可在交接密钥后正常解密/展示，且无密钥时 fail-closed。

## G. 交付签字

归档：包名、包 SHA-256、源码版本、导出人、校验人、恢复验收人、恢复目标、验收时间、问题清单、整改结果、最终签字。

> 只有 A～G 全部完成，才能将“可移交/可迁移”标记为通过；只生成一个压缩包不等于完成迁移验收。
