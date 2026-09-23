# 发布与回退边界

本轮新增 `hr_onboarding.0018_school_template_permissions`，仅改变未托管权限模型的权限元数据，新增配置和发布两项权限；不新增业务表。不能因此跳过V8 payroll.0014或任何既有迁移。前后端和权限需同步发布，不只复制CSS。

在项目根目录并激活完整原依赖环境后运行（用实际原学校ID，切勿猜成1）：
```bash
python manage.py hr_first_delivery_check --tenant-id ACTUAL_TENANT_ID --report /secure-path/first-delivery-check.json
```
这里ACTUAL_TENANT_ID须替换为原学校整数ID；报告路径须为受限运维目录。命令只读，不建库、不迁移、不建人、不发薪。exit2表示技术阻断；exit3表示技术项检查完仍有业务/客户门待验收。即使技术项通过也不会写release_approved=true。

本轮实际SQLite历史迁移在原 `hr_staff.0021_self_submission_seals` 要求MySQL处失败，没有跳过；生产设置检查缺environ依赖。必须在独立MySQL8.4执行原完整迁移、初始化和真实角色验证后再交付。不要将本轮测试数据库、夹具或运行依赖放到生产。

原工资源码、原迁移和许可证逐字节保留；完整原工程仍可继续其他模块施工。存在并行改动时先应用PATCH检查/合并，不能整包覆盖。

生产配置版本/任务/材料事实已经生成后，不要反向删除这些事实来退代码。先冻结新的模板写操作，核对当前事务、回执和旧单；优先前向修复。新增权限迁移逆转不自动删除已经分配的权限记录，需由学校授权人员另行复核撤权。保留新schema和哈希验证服务，不能退到不认识该schema的老代码后继续变更版本。备份恢复必须在独立库实做核对。

当前支持范围之外仍包括完整跨院系/SSO权限、MySQL行锁并发、Windows实机、备份恢复、学校政策和实账签认、真实外部邮件/一卡通等集成；不将这些全部描述为“只差配置”。
