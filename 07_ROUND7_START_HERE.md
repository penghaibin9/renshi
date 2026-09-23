# 跃科高校人事系统：Round7 成熟产品对标与上线前源码收口入口（2026-09-15）

本轮唯一基线：`Yueke_University_HR_Round6_20260915.zip`  
Round6 SHA256：`37ac202014b73c53efe88e63c9e0aec02631fc0b9645e465723c28b3a0bef63d`

施工仅发生在云端源码副本；**未连接 GitHub、未连接生产服务器、未连接生产数据库**。

## Round7 的目的

Round6 已完成 HR01～HR18 主业务源码收口。Round7 不再扩菜单，而是对标成熟高校 HCM 后，把上线前最重要的治理缺口做实：

1. 敏感字段独立加密/指纹/票据密钥真实落到代码；
2. Round6 旧密文兼容读取 + 可审计 rewrap；
3. HR05 Excel 导入从进程内存 Job 改为数据库持久 Job/Row 账本；
4. HR09 Authority 切换改为共享数据库 cutover 真值，不再“临时目录标记/假内存成功”；
5. 增加单租户只读 `go-live-audit`；
6. 把 HR05 Outbox 从“可靠表 + 手工命令”补成持续 `hr05-outbox-worker`，使用 Authority 校验 receipt，禁止重复写 HR03/HR02；
7. 将 HR05 超龄 PENDING/FAILED、HR08 terminal provisioning failure、HR18 dead-letter 与生产 worker 心跳纳入上线阻断；
8. 核验并保留 JY/T 0637-2022、JY/T 0661-2025 标准方向；
9. 更新生产运行手册与上线签字清单。

## 新增/改变的关键操作

### 1. Round6 旧敏感数据升级

```bash
python manage.py rotate_hr_field_security --tenant <TENANT_ID>
python manage.py rotate_hr_field_security --tenant <TENANT_ID> --apply
python manage.py rotate_hr_field_security --tenant <TENANT_ID> --check
```

`hr04_hash_only_unresolved` 必须人工核验/重录或按数据治理流程清理，禁止猜证件号。

### 2. HR09 历史数据切 Authority

先 `DUAL_READ_COMPARE`，完成对账并归档报告号后才允许 `HR09_AUTHORITY`。Authority 模式写入 `HrAuthorityCutover(domain=QUALIFICATION)`；数据库失败即失败，不再输出假成功。

### 3. 正式开流量前单校体检

```bash
make go-live-audit TENANT_ID=<TENANT_ID>
```

这是只读裁决，会检查独立密钥、敏感字段 rewrap、HR01～HR18 Authority、HR05 卡死导入/超龄 outbox、HR08 provisioning、HR18 dead-letter、七类生产 worker/scheduler 心跳和 HR09 cutover。它不会自动改业务数据。

### 4. HR05 Excel

正式 API 已使用 `HrOnboardingImportJob` / `HrOnboardingImportRow` 持久账本；不再使用 `_jobs` 进程内存。确认导入返回 202，并持久记录确认人/确认时间；由 `hr05-import-worker` 以确认人作为审计主体异步提交并可从 crash/restart 恢复；单文件 10 MiB、5000 行，并增加 XLSX archive expansion guard、必需/重复表头与空工作簿拒绝。

### 5. HR05 Outbox

生产 Compose 必须看到 `hr05-outbox-worker` healthy。该 worker 不重放 Activation Authority 写入，只校验已经封存的 HR05/HR03 事实并 ACK。`go-live-audit` 中只要有超 15 分钟 PENDING 或 FAILED，禁止开放流量。

## 市场对标后的产品判断

Round7 后，系统主干已经覆盖成熟高校 HCM 常见核心：组织/岗位、人员主档和历史、多任职、招聘入职、异动合同、外聘、资质/培训、考勤考核、职称聘任、薪酬福利、退休离校、自助、数据中心、权限审计和 Excel。

以下保留为后续竞争力迭代，不再作为首发上线阻断：

- 通用低代码流程/表单设计器；
- 原生移动端完整 HR；
- AI 招聘/人才洞察助手。

详细矩阵和安全修复见：

`docs/reports/HR_ROUND7_MARKET_LAUNCH_CLOSURE_2026-09-15.md`

## 当前发布边界

Round7 只能在本云端环境完成源码级验证。该环境没有 Docker/Django/MySQL 生产运行时，因此：

- 不得标记 `RELEASED`；
- 必须在独立 QA 机执行 `make acceptance-qa`；
- 必须在目标学校候选配置执行 `make go-live-audit TENANT_ID=<id>`；
- 必须完成浏览器黄金流程、备份恢复、真实 SMTP/IAM/财税/签章联调后才能开放流量。

**下一步原则：如果 QA 报错，只修真实失败；不要重新扩 HR01～HR18 菜单。**
