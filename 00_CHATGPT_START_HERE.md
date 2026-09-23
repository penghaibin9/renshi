> **本包已完成“业务流程易用性 + 零基础办理助手”收口，请先阅读 `USABILITY_START_HERE.md`；采购/部署总门仍以 `FINAL_ACCEPTANCE_START_HERE.md` 为准。**

> **本包已完成采购级一次性源码收口，请优先阅读 `FINAL_ACCEPTANCE_START_HERE.md`。** Round2～Round11 文档仅作历史施工证据；当前状态是 `SOURCE_CODE_COMPLETE / RUNTIME_AND_EXTERNAL_ACCEPTANCE_PENDING`，发布必须以真实 Django/MySQL/Docker、100 并发和学校外部接口/试运行/培训验收证据为准。

# 高校人事管理系统：ChatGPT 接手开发说明

## 交付边界

这是依据本机正式工程 `01_项目源码/高校人事系统主程序` 制作的可开发源码快照。打包时只读取工程并制作交付物，未重构、删除或修改任何业务源码；也不依赖 GitHub。

- 本地基线：`main`，本地提交 `9b7f8773`；打包前工作区为干净状态。
- 压缩包内目录就是项目根目录：先阅读本文件，再阅读根目录 `README.md`、`docs/开发顺序_接管版.md` 与对应模块的 `docs/modules/` 文档。
- 本包未包含 Git 历史目录 `.git`；接手开发不依赖 GitHub。需要版本控制时，可在解压后的目录自行初始化本地 Git 仓库。

## 技术栈

- 后端：Python、Django 5.2.17、Django REST Framework；依赖见 `requirements.txt` 和精确锁定文件 `requirements.lock`。
- 前端：Django Templates + 原生 JavaScript/SCSS/CSS 静态资源；Tailwind CSS 3.4.19；依赖见根目录 `package.json` 与 `package-lock.json`。
- 数据库：MySQL-only，Docker Compose 默认镜像为 MySQL 8.4；另使用 Redis 7。
- 部署：Dockerfile、`docker-compose.yml`、`docker-compose.prod.yml`、`docker-compose.dbport.yml`、`deploy/`、Makefile、`scripts/`。
- 表结构：Django model 与 `backend/*/migrations/` 中的迁移文件。预检未发现 Alembic 或独立 `.sql` 迁移文件，这是本工程当前的实际实现方式。

## 首次启动

推荐使用 Docker Desktop、Docker Compose、Python 和 Node.js 的当前稳定版。所有命令在本包解压根目录执行。

1. 复制配置模板并填写本机开发所需值：`Copy-Item .env.dist .env`。`.env.dist` 仅是字段模板；请自行配置 `SECRET_KEY`、MySQL/Redis 密码、邮件、加密密钥和外部接口 Token，切勿提交 `.env`。
2. 启动开发环境：`docker compose up -d --build`。如系统已装 GNU Make，也可使用 `make dev`。
3. 执行迁移与一致性检查：`docker compose run --rm web sh -c "python manage.py makemigrations --check --dry-run && python manage.py migrate --noinput && python manage.py migrate --check"`，或使用 `make migrate`。
4. 检查服务：`docker compose run --rm web python manage.py check`，或使用 `make check`。
5. 仅在需要演示环境时，按 `backend/load_data/README.md` 使用 `python manage.py load_demo_data --flush --no-input`。该命令会清空目标库，不能用于已有业务数据的数据库。

原工作区仍可优先双击 `F:\高校人事系统\03_启动工具\1_启动人事系统.cmd` 启动、`F:\高校人事系统\03_启动工具\2_停止人事系统.cmd` 停止；这两个外层启动工具不属于正式源码仓库，因此未复制进本包。

## 主要目录

- `backend/`：Django 项目、业务应用、API、模型、服务、权限、迁移、模板和静态资源。
- `frontend/`：前端模板、原始静态资源、HR01--HR18 页面资源。
- `docs/`：模块说明、开发顺序、验收、重构与报告文档。
- `tests/` 与各 `backend/*/tests*`：现有自动化与视觉回归测试源码；仅去除了可重新生成的截图产物。
- `deploy/`、`scripts/`、Docker/Compose 文件、Makefile：本地与容器化部署、检查和辅助脚本。
- `backend/load_data/`：经预检的演示 fixture、图标和头像，以及演示数据装载说明。

## 已有业务功能

HR01--HR18 代码和文档均已在本包保留：人事工作台；组织机构与编制岗位；教职工主档；招聘与人才引进；入职；人事异动；合同与聘用；兼职外聘教师；教师资格与双师型；培训进修与企业实践；考勤与请假；年度与聘期考核；职称评审；岗位聘任；薪酬福利；退休与离校；教职工服务；人事数据中心。

同时保留了 RBAC/多租户与权限相关代码（如 `platform_access`、`horilla_auth`、各模块 permissions/policies）、审计（`horilla_audit`、`django-auditlog`）、文件上传下载（`horilla_documents` 及模块服务）、Excel 导入导出（`django-import-export`、`openpyxl`、`XlsxWriter` 和各模块 service/API）、PDF/打印与报表（`report`、`base/pdf.py`、报表模板）。

## 测试命令

以下命令以 MySQL 环境为准：

```text
make check
make test
make test-hr
docker compose run --rm web python manage.py test --noinput --verbosity 1
docker compose run --rm web python manage.py test base hr_control_center hr_structure hr_staff hr_recruitment hr_onboarding hr_changes hr_contracts hr_external hr_qualification hr10_development hr_time hr_assessment hr_title hr_appointment hr_payroll hr_exit hr_self hr_data --noinput --verbosity 1
npm ci
npm run build:css
```

视觉回归测试源码位于 `tests/visual/`；运行前按各测试文件的浏览器、服务地址和数据准备要求配置环境。

## 已知事项与接手原则

- 本工程没有一份可直接视为“当前缺陷清单”的统一问题台账。预检发现约 159 个含 TODO/FIXME/“待办”等词的文件命中，其中也包含待办业务本身、文案和测试；不能自动等同于未完成缺陷，应逐项判断。
- `README.md` 明确要求保留 MySQL-only、租户、权限、审计和 Authority Cutover 边界；不要为了测试通过而关闭这些控制。
- 打包前未检测到新的未提交源码修改；本次没有收到具体待改业务项。后续修改应先确定所属 HR 模块，再依据 `docs/开发顺序_接管版.md` 和模块测试执行。
- 未发现 Alembic 或 SQL 迁移；新增表结构应遵循现有 Django migration 机制，不要凭空引入第二套迁移体系。

## 安全与已排除内容

本包包含 `.env.dist` 配置字段模板，但不含任何实际 `.env`、数据库、数据库密码、服务器密码、API Key、Token、证书私钥或运行时日志。为避免打包固定的开发数据库和 Redis 口令，包内 `docker-compose.yml` 将这些口令改为读取 `.env` 的 `MYSQL_PASSWORD` 和 `REDIS_PASSWORD`；正式源工程未被改动。演示 fixture 已做结构性检查：未命中中国身份证号或中国手机号；其演示邮箱域名主要为 `university.example`。压缩规则和关键清单见 `01_FILE_MANIFEST.txt`。

本说明仅描述本地已核验的源码快照，不替代目标环境的部署验收。首次接手后请先按“首次启动”和“测试命令”完成环境验证，再开始业务修改。
