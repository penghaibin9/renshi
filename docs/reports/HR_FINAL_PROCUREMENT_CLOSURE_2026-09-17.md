# 跃科高校人事系统采购级最终源码收口报告

日期：2026-09-17  
基线：Round11  
裁决：**SOURCE_CODE_COMPLETE / RUNTIME_AND_EXTERNAL_ACCEPTANCE_PENDING**

## 1. 本轮不是继续堆业务菜单

采购参考最有价值的内容是学校项目真实验收边界：权限与数据范围、基础初始化、接口映射/同步/失败重试、教师资质历史依据、考核版本与异议、审计与附件、部署性能、独立交付、培训售后和供应商退出后的数据可迁移。Round9～Round11 已经覆盖 HR10 身份/导入、HR18 同步和开放移交，本轮把剩余可由源码完成的采购级交付能力一次性收口。

## 2. 真实修复：RBAC

旧 `user_group_permission_remove(request,pid,gid)` 虽然 URL 带目标 ID，函数内部却固定修改 `Group(id=1)` / `Permission(id=2)`。本轮改为精确锁定 URL 指定角色并移除精确 Permission；不存在的关系作为幂等 no-op。

同时增加角色权限复制：只复制 `Group.permissions`，不复制 `user_set`，不创建 `CompanyGroupAssignment`。新角色默认没有成员、没有组织数据范围，避免“复制角色=复制访问主体”的隐性提权。

进一步把权限管理 POST 从裸 codename 升级为 `app_label.codename`。兼容旧裸 codename 时只有全库唯一才接受，重复时 fail-closed，不再通过 `codename__in` 把其他 app 的同名权限一并授权。

## 3. 学校初始化快照

新增 `export_school_initialization_snapshot`：输出 JSON + detached SHA256，记录组织/字典、安全可公开配置、角色及精确权限、管理员账号清单、HR18 接口映射、migration 状态。快照显式声明并过滤密码、Token、私钥、API Key 和字段加密密钥；密钥继续通过独立安全通道配置。

## 4. 最终采购证据包

新增 `build_procurement_acceptance_package.py`。它只接受机器可校验的真实证据：

- runtime acceptance 必须 PASSED，且包含 migration、HR01～HR18 MySQL 测试、初始化快照、灾备/移交恢复、ready；
- performance 必须 PASS、并发 >=100、普通阈值 <=3000ms、复杂统计 <=5000ms，并同时包含 NORMAL / ANALYTICS；
- trial run 必须所有抽样流程 PASS，并有采购人/供应商代表及双方确认；
- remediation 每行必须 CLOSED + PASS + ACCEPTED；
- training 至少覆盖 ADMIN + OPERATOR，且 COMPLETED + CONFIRMED；
- external integrations 必须 REQUIRED→PASS，或 NOT_APPLICABLE→理由 + 双方确认。

只有全部成立才生成 `release_certificate.json`；否则只生成 `INCOMPLETE` 诊断包。

## 5. 交付材料

新增：HR01～HR18 用户操作手册、管理员培训、经办培训、售后 SLA、试运行模板、整改台账、培训记录、外部接口验收模板、最终验收 checklist、14 项采购参考对照矩阵。

## 6. 本轮实跑结果

- HR10 import static：20/20 PASS
- HR10 staff identity：53/53 PASS
- HR18 procurement sync：24/24 PASS
- school handover：33/33 PASS
- final procurement source closure：53/53 PASS
- pure tests：187/187 PASS
- Python AST：3159 files / 0 errors
- JavaScript node check：253 files / 0 errors

当前执行器没有 Django、没有 Docker；这两项已真实探测失败，因此未声称完成真实 MySQL/Compose 动态验收。

## 7. 发布原则

源码现在可以作为最终源码候选基线。后续不再以新增菜单作为主线；只补目标环境真实验收证据。正式放行要求：runtime + performance + external integrations + trial run + remediation + training 全部闭环，最终 evidence pack 为 COMPLETE，之后再走学校正式签字/验收流程。
