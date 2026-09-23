# 跃科高校人事系统 V16 配置中心 V1 + Integration Hub V1 施工报告

## 1. 基线与范围

- 唯一源码基线：`Yueke_University_HR_UIA_V16_RepoClean_20260920.zip`
- 本轮不新增 HR19/HR20。
- 不重写 HR01～HR18 既有业务事实、状态机和 Authority。
- 新能力只挂到“系统管理”，定位为学校级实施基础设施。

## 2. 已完成：高校人事配置中心 V1

八层配置完整落地：

1. 流程 `WorkflowDefinition / WorkflowVersion / WorkflowStage`
2. 表单 `FormDefinition`
3. 字段 `FieldDefinition`
4. 审批角色 `ApprovalRoleRule`
5. 条件 `ConditionRule`
6. 通知 `NotificationRule`
7. 打印模板 `PrintTemplate`
8. Excel 模板 `ExcelTemplate / ExcelColumn`

生产边界：

- 草稿可编辑；发布必须通过阶段、表单、审批、条件、Excel 字段引用校验。
- 发布生成 SHA-256 内容指纹和稳定 JSON 合同。
- 发布后版本及子项禁止普通 save/update/delete/bulk_update/bulk_create 改写。
- 后续变化通过“复制为新草稿 → 修改 → 再发布”，保留历史规则。
- 所有写操作使用服务端解析出的 tenant，浏览器不接受 tenant_id。
- 追加式配置审计记录新增/修改/删除/复制/发布。
- 提供稳定读取接口 `get_published_workflow_config()` 与 HTTP contract API。
- 初始化命令只创建 HR04/05/06/12/13/14/16/17 草稿骨架，不自动发布学校规则。

## 3. 已完成：高校人事 Integration Hub V1

Adapter Registry 已提供：

| 领域 | Adapter |
|---|---|
| SSO | CAS / OAuth2 / OIDC / LDAP(LDAPS) |
| 组织人员 | 数据中台 / 主数据 HTTP JSON |
| 科研 | 项目 / 论文 / 成果 HTTP JSON |
| 教务 | 课程 / 教学工作量 HTTP JSON |
| 财务 | 工资支付 / 凭证 / 成本中心 HTTP JSON |
| 考勤 | 门禁 / 一卡通 / 考勤机 HTTP JSON |
| 电子签章 | HTTP JSON |
| 通知 | 短信 HTTP / SMTP 邮件 / 企业微信 |

实现能力：

- 学校级 `IntegrationConnection`；
- 映射方案与字段映射；
- Adapter 类别/必填配置/密钥合同校验；
- 密钥使用现有 `FIELD_ENCRYPTION_KEYS` 加密，页面只写不回显；
- 修改普通连接配置时复用已加密密钥，不要求重复录入；
- Adapter 必需密钥缺失或密钥字段不对时禁止启用；
- 合同 API 永不返回密钥；
- HTTP/SMTP 探测受 `HR_INTEGRATION_ALLOWED_HOSTS` 白名单约束；HTTP 不跟随重定向；
- 测试与审计证据采用追加式模型，阻止 QuerySet update/delete/bulk_update；
- 映射方案和字段映射的新增/删除均留审计；
- LDAP V1 明确只做配置合同和目标主机白名单校验，不伪造真实 bind 成功。

## 4. “换学校不改 HR01～HR18”的代码边界

新增稳定门面：`backend/horilla/hr_school_contracts.py`

- `school_workflow(...)`
- `school_integration(...)`

业务模块以后只从该门面取得“已发布学校流程合同”和“已启用学校连接合同”；学校厂商 URL、凭据、字段名和映射不进入 HR01～HR18。

本轮没有私自把 HR04/05/06/12/13/14/16/17 的现有状态机改成动态引擎，避免改变已验收业务 Authority。V1 先把稳定合同和学校级配置事实建好。

## 5. 系统管理入口

新增：

- `/settings/hr-configuration/`：高校人事配置中心
- `/settings/integration-hub/`：高校人事 Integration Hub

原 HR18 `/hr/data/exchange/` 保留，系统管理显示为“数据上报与交换”，继续负责正式业务上报/回执/修正；Integration Hub 负责连接、Adapter 和字段映射。

## 6. 实际验证结果

### 6.1 迁移漂移

`makemigrations hr_configuration hr_integration --check --dry-run`

- 结果：`No changes detected`

### 6.2 隔离 Django 服务/模型测试

- 11 tests
- 11 passed
- 覆盖：发布不可变、批量篡改拦截、草稿复制、tenant 预绑定、密钥加密/不回显、已有密钥复用、错误密钥禁止启用、未知 Adapter 变表单错误、映射租户绑定、测试/审计 append-only。

### 6.3 源码合同门

- 6 passed
- 覆盖：不新增 HR19/20、系统管理入口、八层配置、Adapter 全目录、密钥边界、稳定 school contract facade。

### 6.4 默认草稿初始化幂等

同一 tenant 连续执行两次：

- 第一次 `created workflows=8`
- 第二次 `created workflows=0`
- 最终 workflow=8
- draft=8
- published=0
- stage=41
- form=8

说明初始化不会重复造流程，也不会自动发布未经学校确认的制度。

### 6.5 RepoClean 前端边界

`scripts/audit_hr_frontend_boundary.py`

- `pass=true`
- `old_index_parent_count=0`
- `legacy_component_reference_count=0`
- `hardcoded_old_ui_link_count=0`

新增页面继续继承 V16 `hr/base.html`，没有把 Horilla 旧 shell 引回来。

### 6.6 Python 语法

新 App、管理命令、测试、稳定合同门面均完成 `py_compile`。

## 7. 仍然是生产验收门，不冒充已完成

当前执行环境没有 Docker CLI，无法启动与生产同构的 MySQL 8.4 环境；也没有学校真实 SSO、主数据、科研、教务、财务、考勤、签章、短信/邮件/企业微信端点和凭据。

因此本轮可确认的是：**V1 源码、迁移、隔离服务规则、配置发布不可变、密钥安全边界、租户边界、初始化幂等、RepoClean shell 边界已通过当前可执行验证。**

正式部署前仍必须在学校/腾讯云独立 MySQL 8.4 环境完成：

`migrate → 权限 → bootstrap → 浏览器创建/发布配置 → Integration Hub 建连接/映射 → 白名单连通测试 → 真实 SSO/数据接口验收 → 备份恢复。`

## 8. 部署最短路径

```bash
python manage.py migrate
python manage.py bootstrap_hr_configuration_v1 --tenant <本校tenant_id> --actor <管理员user_id>
```

环境变量：

```dotenv
FIELD_ENCRYPTION_KEYS=<沿用V16正式字段密钥环>
HR_INTEGRATION_ALLOWED_HOSTS=sso.school.edu.cn,data.school.edu.cn
HR_INTEGRATION_HTTP_TIMEOUT_SECONDS=5
```

随后由本校系统管理员在“系统管理”中完成配置和 Adapter 实例，不需要把学校 URL、账号、字段名写进 HR01～HR18 源码。
