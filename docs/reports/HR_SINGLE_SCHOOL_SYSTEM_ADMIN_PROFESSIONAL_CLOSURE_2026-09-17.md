# 高校人事系统：单校独立部署版系统管理专业化收口报告

## 1. 结论

本轮把学校系统管理从“设置入口集合”升级为“单校独立部署的管理控制台”。系统管理员不需要理解 SaaS 租户、套餐或平台主管语义；日常只围绕本校账号、组织、权限、参数、安全、接口和灾备工作。

## 2. 单校边界

- 部署模式显式为 `standalone_school`；
- 正常管理界面只允许一个学校主体；
- 二级学院、职能处室、系部一律进入组织/部门层级；
- 唯一学校存在时，部门表单自动绑定本校；
- 平台临时提升权限 API 默认不发布；
- 本地超级管理员只允许写入唯一学校，若出现多个学校主体则 fail-closed。

## 3. 管理员首页

任务入口固定为：

- 学校基本信息
- 账号与人员
- 角色与权限
- 组织与部门
- 岗位与职务
- 基础参数
- 安全审计
- 邮件与通知
- 接口与同步
- 运行与备份

同时保留自然语言搜索，例如“开账号、配角色、加学院、查日志、备份”。

## 4. 专业运行检查

页面实时读取现有 Authority/配置，只生成只读状态：

- 学校主体是否唯一；
- 组织/岗位是否已建立；
- 是否存在未分角色账号；
- 是否存在个人直接授权；
- 数据库是否为 MySQL；
- DEBUG/Secret Key/字段加密/Allowed Hosts 是否符合生产基线；
- 管理员 MFA 是否开启；
- 学校 SMTP 是否已配置；
- 是否能识别最近生产备份 Manifest；
- 单校版是否误开启平台主管接口。

不读取或展示真实密码、SMTP 密码、Token、FIELD_ENCRYPTION_KEYS、备份密钥内容。

## 5. 权限治理

继续沿用既有 RBAC，不建立第二权限体系：

- 角色优先，个人直接授权仅作为例外；
- 复制角色只复制 Permission，不复制成员和组织范围；
- Delete 类高风险权限需要二次确认；
- 单校学校管理员不等于平台主管；
- 审计员只读，不参与业务修改；
- 平台支持接口在当前独立版默认关闭。

## 6. 运维边界

网页不提供数据库“一键恢复”。生产备份、校验、隔离恢复、学校数据移交仍使用服务器端受控命令与现有 Manifest/SHA 机制。

新增：

```bash
python manage.py check_school_system
python manage.py check_school_system --json
```

阻断项存在时命令返回失败，适合作为部署/升级后的检查门。

## 7. 回归

- 205 passed + 25 subtests；
- System Admin source contract 31/31 PASS；
- HR usability 102/102 PASS；
- System Admin Chromium PASS；
- HR lifecycle Chromium PASS；
- Python AST 3168/3168；
- JavaScript 256/256。

## 8. 发布状态

源码侧：`SINGLE_SCHOOL_SYSTEM_ADMIN_SOURCE_COMPLETE`。  
运行侧：`DJANGO_MYSQL_SCHOOL_ACCEPTANCE_PENDING`。
