# 跃科高校人事系统 V16：配置中心 V1 + Integration Hub V1

> 基线：`Yueke_University_HR_UIA_V16_RepoClean_20260920`  
> 施工日期：2026-09-23  
> 原则：不新增 HR19/HR20；不重写 HR01～HR18 的业务事实与 Authority；新增能力只作为学校级基础设施挂入“系统管理”。

## 1. 这轮解决什么

### 高校人事配置中心 V1

只覆盖学校实施最常变化的八层配置：

`流程 → 表单 → 字段 → 审批角色 → 条件 → 通知 → 打印模板 → Excel 模板`

首批提供默认草稿骨架的业务域：HR04、HR05、HR06、HR12、HR13、HR14、HR16、HR17。

核心规则：

- 草稿可编辑；发布前做引用完整性校验。
- 发布生成稳定 JSON 合同与 SHA-256 指纹。
- 已发布版本不可普通 `save/update/delete/bulk_update` 改写；变更必须从已发布版本复制新草稿。
- 默认初始化只创建草稿，不自动发布学校制度。
- 所有配置写操作均绑定服务端解析出的学校 `tenant_id`，浏览器不能提交学校 ID 改写租户。
- 组件新增、修改、删除、发布、复制草稿均写追加式审计。

### 高校人事 Integration Hub V1

标准 Adapter Registry：

- SSO：CAS / OAuth2 / OIDC / LDAP(LDAPS)
- 组织人员：数据中台 / 主数据 HTTP JSON
- 科研：项目 / 论文 / 成果 HTTP JSON
- 教务：课程 / 教学工作量 HTTP JSON
- 财务：工资支付 / 凭证 / 成本中心 HTTP JSON
- 考勤：门禁 / 一卡通 / 考勤机 HTTP JSON
- 电子签章：HTTP JSON
- 通知：短信 HTTP / SMTP 邮件 / 企业微信

学校级变化落在三处：

1. `IntegrationConnection`：地址、非敏感参数、启停状态；
2. `IntegrationMappingProfile/IntegrationFieldMapping`：外部字段 ↔ 人事字段；
3. `Adapter`：只有协议或厂商行为确实不同才新增/替换 Adapter。

密钥：

- 使用 V16 已有 `FIELD_ENCRYPTION_KEYS` 字段密钥环加密；
- 页面只写不回显；
- 合同 API 永不返回密钥；
- 编辑普通配置时可复用已加密密钥，不要求管理员重新输入；
- Adapter 所需密钥项缺失时禁止启用连接。

网络探测：

- 后台探测只允许访问 `HR_INTEGRATION_ALLOWED_HOSTS` 白名单；
- HTTP 禁止自动跟随重定向；
- 超时由 `HR_INTEGRATION_HTTP_TIMEOUT_SECONDS` 控制；
- LDAP V1 只做配置合同/白名单校验，不冒充真实绑定成功；正式 LDAP bind 留给部署验收环境。

## 2. 稳定消费合同

业务模块以后只应依赖：

- `horilla.hr_school_contracts.school_workflow(...)`
- `horilla.hr_school_contracts.school_integration(...)`

不要让 HR01～HR18 直接读 `hrcfg_*` / `hrint_*` 数据表，也不要把某学校 URL、账号、字段名写回业务模块。

这样换学校时，优先变化的是“发布配置 + 连接实例 + 字段映射 + Adapter”，而不是 fork HR01～HR18。

## 3. 系统管理入口

新增两个入口：

- **高校人事配置中心**：`/settings/hr-configuration/`
- **高校人事 Integration Hub**：`/settings/integration-hub/`

原 HR18 的 `/hr/data/exchange/` 继续保留，但系统管理显示为“数据上报与交换”：它仍负责正式业务上报、回执、修正、对账；Integration Hub 负责基础设施连接和映射，二者不混为一个 Authority。

## 4. 首次部署步骤

在学校的正式 V16 环境中执行，而不是在本施工容器中冒充生产验收：

```bash
python manage.py migrate
python manage.py bootstrap_hr_configuration_v1 --tenant <本校tenant_id> --actor <管理员user_id>
```

然后：

1. 给本校系统管理员组配置 `hr.configuration.view/manage/publish` 和 `hr.integration.view/manage/test` 对应权限；
2. 在环境变量中保留/配置 `FIELD_ENCRYPTION_KEYS`；
3. 将允许由后台发起连接测试的学校接口主机加入 `HR_INTEGRATION_ALLOWED_HOSTS`；
4. 进入配置中心逐条补齐字段、审批角色、条件、通知、打印、Excel，再发布；
5. 进入 Integration Hub 建连接、录密钥、建字段映射、做连通性测试；
6. 最终在真实 MySQL 8.4 + 学校网络环境做迁移、权限、浏览器和实际接口验收。

## 5. 本轮明确没有做的事

- 没有新增 HR19/HR20。
- 没有重写 HR01～HR18 已存在的业务状态机、人员事实、薪酬事实或数据中心事实。
- 没有把“配置中心”做成任意脚本/任意 SQL 的万能低代码平台。
- 没有在无学校网络、无正式凭据环境下宣称 CAS/OIDC/LDAP/财务/签章等真实对接已经成功。
- 没有把 SQLite 隔离单测当作 MySQL 8.4 生产验收。
