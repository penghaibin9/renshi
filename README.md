# 跃科高校人事管理与教师发展系统

`renshi` 是湖南跃科信息工程有限公司面向高校与职业院校建设的人事管理与教师发展产品代码库，覆盖从组织编制、教职工主档、招聘入职、合同异动，到资格发展、考勤考核、薪酬离校、教职工服务和人事数据中心的一体化业务链路。

> 当前主干：`main`  
> 技术栈：Django + MySQL + Redis  
> 产品范围：HR01–HR18  
> 数据边界：多学校 / 多租户隔离、权限、审计、历史有效期与跨域 Authority 合同

## 产品能力

| 模块 | 能力 |
|---|---|
| HR01 | 人事工作台 |
| HR02 | 组织机构与编制岗位 |
| HR03 | 教职工主档 |
| HR04 | 招聘与人才引进 |
| HR05 | 入职管理 |
| HR06 | 人事异动 |
| HR07 | 合同与聘用 |
| HR08 | 兼职外聘教师 |
| HR09 | 教师资格与双师型 |
| HR10 | 培训进修与企业实践 |
| HR11 | 考勤与请假 |
| HR12 | 年度与聘期考核 |
| HR13 | 职称评审 |
| HR14 | 岗位聘任 |
| HR15 | 薪酬福利 |
| HR16 | 退休与离校 |
| HR17 | 教职工服务 |
| HR18 | 人事数据中心 |

## 核心工程原则

本仓库按高校人事领域 Authority 划分正式事实源。跨域写入通过明确的 Service / Command / Event 合同完成，不允许下游模块直接修改其他领域的正式事实。

- **MySQL-only**：开发、测试、CI、迁移验收与生产统一以 MySQL 为数据库目标。
- **Tenant fail-closed**：学校上下文不明确时拒绝访问，不以默认学校或全量范围兜底。
- **Permission & Audit**：关键操作必须经过权限判定并保留审计证据。
- **Effective-dated**：组织、任职、合同等历史事实以有效期和修订语义保留历史，不直接覆盖过去。
- **Idempotency & concurrency**：正式业务命令关注幂等、事务、锁与并发一致性。
- **Production gates**：代码、迁移、权限负测、跨域 E2E、备份恢复与安全门禁共同决定可交付状态。

## 代码结构

```text
hr_control_center/     HR01 人事工作台
hr_structure/          HR02 组织机构与编制岗位
hr_staff/              HR03 教职工主档
hr_recruitment/        HR04 招聘与人才引进
hr_onboarding/         HR05 入职管理
hr_changes/            HR06 人事异动
hr_contracts/          HR07 合同与聘用
hr_external/           HR08 兼职外聘教师
hr_qualification/      HR09 教师资格与双师型
hr10_development/      HR10 培训进修与企业实践
hr_time/               HR11 考勤与请假
hr_assessment/         HR12 年度与聘期考核

docs/                  产品架构、模块设计与生产验收资料
.github/workflows/      CI / 生产级门禁
horilla/                Django 工程配置及兼容底座
```

HR13–HR18 的具体代码目录与跨域依赖以 [`docs/00_文档总索引.md`](docs/00_文档总索引.md) 为准。

## 文档入口

- [`docs/00_文档总索引.md`](docs/00_文档总索引.md)：当前产品与工程文档导航。
- [`docs/00_高校人事系统全局架构与Horilla接管合同.md`](docs/00_高校人事系统全局架构与Horilla接管合同.md)：历史命名保留的全局架构合同，仍承载 Authority、租户、历史事实、Provider/Event 与数据库规则。
- HR01–HR18 模块总册：各领域业务规则、状态机、边界与验收口径。
- `docs/hr/`：模块 GAP、风险、验收和迁移资料。
- `docs/archive/`：阶段性施工说明、旧状态快照与上游来源说明，不作为当前完成状态依据。

判断当前实现状态时，以 **当前 `main` 代码 + 当前 CI/测试结果** 为准，不以历史阶段报告中的 `READY`、`FINAL` 或旧分支状态作为单独依据。

## 本地开发

```bash
# 创建本地环境配置
cp .env.dist .env

# 按项目现有开发方式启动依赖与应用
# 数据库目标统一为 MySQL
```

具体环境变量、迁移和测试入口请以仓库中的 `.env.dist`、`docker-compose.yml`、`Makefile` 与 CI 配置为准。

## 品牌与来源

“跃科高校人事管理与教师发展系统”为本仓库当前产品身份。仓库早期代码基于开源 HRMS 项目演进，并保留了兼容层、历史包名和必要的来源记录；这些技术遗留不会作为当前产品的用户可见品牌。

上游来源与迁移背景统一归档在 [`docs/archive/upstream/README.md`](docs/archive/upstream/README.md)。内部包名与历史代码标识仅在不影响兼容性的前提下逐步治理，不通过一次性大规模重命名处理。

## License

本次产品化与仓库身份整理不修改许可证。许可证文本与适用要求以 [`LICENSE`](LICENSE) 为准。
