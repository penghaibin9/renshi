# 跃科高校人事系统：采购级最终源码候选版接续入口

日期：2026-09-17  
基线：`Yueke_University_HR_Round11_20260917.zip` → 本次一次性采购级收口  
状态：**SOURCE_CODE_COMPLETE / RUNTIME_AND_EXTERNAL_ACCEPTANCE_PENDING**

## 1. 本次一次性收口完成项

本次继续以用户提供的 9 页《一站式非学历教育智慧前台建设项目采购清单》作为高校项目验收参考，但只吸收高校人事系统适用的共性能力，不把培训收入、课程人次、省级非学历业务等专属功能硬塞进 HR01～HR18。

源码级已完成：

- 修复角色权限删除接口忽略 URL 参数、写死 `Group=1 / Permission=2` 的真实 RBAC 缺陷；
- 角色权限复制：只复制 Permission，不复制成员、不复制学校/组织数据范围；
- 权限选择从裸 codename 升级为 app-qualified permission reference，歧义旧值 fail-closed，避免同名 codename 误授权；
- 新增学校上线初始化快照：基础字典/组织、角色权限、管理员、非密钥运行参数、HR18 接口映射、Django migration 状态，附 detached SHA256；
- 最终 acceptance harness 接入初始化快照，并可在真实运行验收通过后继续生成最终采购证据包；
- 保留 Round10 的 100 并发 / 普通页面 3 秒 / 复杂统计 5 秒可执行性能门；
- 保留 Round11 的加密灾备、开放格式学校移交、SHA/Manifest 校验、第二空库恢复、逐表精确行数比对；
- 新增管理员培训手册、经办人员培训手册、HR01～HR18 用户操作手册、售后 SLA 基线；
- 新增试运行记录、整改台账、培训记录、外部接口验收的机器可校验模板；
- 新增最终采购验收证据包生成器：缺真实运行、性能、试运行双方确认、整改闭环、ADMIN+OPERATOR 培训或外部接口证据时，只能生成 `INCOMPLETE`，不得生成 `release_certificate.json`；
- 新增 14 项采购参考对照矩阵，明确适用 / 共性能力适用 / 不直接适用，禁止把非学历教育教师积分业务伪装成人事功能。

## 2. 当前已实跑的源码门

- HR10 Excel 真导入静态门：20 / 20 PASS
- HR10 HR03 UUID 人员身份门：53 / 53 PASS
- HR18 采购同步门：24 / 24 PASS
- 学校开放格式移交门：33 / 33 PASS
- 最终采购级源码门：53 / 53 PASS
- Round2～Round11 + final pure tests：187 / 187 PASS
- 全仓 Python AST：3,159 文件，0 错误
- JavaScript `node --check`：253 文件，0 错误

## 3. 本环境不能伪造完成的事项

### RUNTIME_PENDING
当前执行器真实执行 `python manage.py check` 返回 `ModuleNotFoundError: No module named 'django'`；`docker compose version` 返回 `docker: command not found`。因此本会话不能真实运行 MySQL 8.4 / Redis / ClamAV / Django / Compose，也不能冒充完成迁移、数据库回归、恢复后的 Web `/ready/` 或 100 并发性能证据。

### EXTERNAL_PENDING
学校统一认证、学校数据中台、省级平台或其他合同接口，只有拿到采购人提供的真实规范、账号/证书/白名单、字段字典和责任边界后才能联调。没有对方条件时必须保持 PENDING 或由采购人/供应商双方确认 NOT_APPLICABLE，禁止 mock 成 PASS。

### HUMAN_ACCEPTANCE_PENDING
真实试运行、整改关闭、管理员/经办培训需要学校代表参与。源码只提供严格模板与验证器，不自行填写“已确认”。

## 4. 目标环境最终总门

```bash
python scripts/run_hr_acceptance_gate.py \
  --project yueke_hr_final_acceptance \
  --procurement-pack-output /secure/evidence/Yueke_HR_Final_Acceptance_Evidence.zip \
  --procurement-performance-json /secure/evidence/performance.json \
  --trial-run-record /secure/evidence/trial-run.json \
  --remediation-register /secure/evidence/remediation.csv \
  --training-record /secure/evidence/training.csv \
  --external-integration-record /secure/evidence/external-integrations.json
```

只有该链真实完成，且最终证据包 `acceptance_summary.json` 为 `COMPLETE`、`releaseCertificate=true`，才进入采购验收签字候选；采购人的正式签章和合同验收仍以实际项目流程为准。

## 5. 下一步边界

不要再用“继续加菜单”作为上线前主线。下一步只做目标环境真实验收：Django/MySQL/Compose、100 并发、学校接口联调、试运行、整改、培训和正式签字证据。
