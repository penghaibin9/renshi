# 跃科高校人事系统 Docker 指南

本仓库的开发、测试、迁移和生产签字数据库统一为 **MySQL 8.4**。Redis 7 用于缓存与运行时协调；Django/Gunicorn 提供 Web 服务。旧文档中的 PostgreSQL 命令不适用于当前系统。

HR03～HR18 的正式事实使用 MySQL Trigger 作为数据库层防篡改兜底。Compose 已启用 `log_bin_trust_function_creators=1`，使不具备 `SUPER` 权限的专用 migration 用户可以在开启 binary log 的 MySQL 8.4 上安装这些触发器；外部托管 MySQL 也必须由 DBA 配置同等能力，禁止给日常 Web 账号授予 `SUPER`。

## 新手本地启动

需要 Docker Desktop（含 Docker Compose）。开发栈自带本地开发凭据，不需要先配置数据库：

```bash
make dev
```

首次构建会安装依赖、启动 MySQL/Redis、执行入口脚本并启动 Web。浏览器访问 `http://localhost:8000`。常用命令：

```bash
make status       # 查看服务状态
make logs-web     # 查看 Django/Gunicorn 日志
make check        # Django 系统检查
make migrate      # 检查并执行 MySQL migration
make test-hr      # HR01~HR18 注册测试
make stop         # 停止服务，保留数据
```

`make clean` 会删除本项目 Compose 数据卷，只能在明确需要清空本地测试数据时使用。

## 本机连接 MySQL

主 Compose 不向宿主机暴露数据库端口。需要临时从本机工具连接时：

```bash
docker compose -f docker-compose.yml -f docker-compose.dbport.yml up -d db
```

连接 `127.0.0.1:13306`。容器内部始终使用 `db:3306`。也可直接运行 `make db-shell`。

## 生产 Compose

生产环境使用基础文件加生产 overlay：

```bash
cp .env.dist .env
# 把 .env 中每个 change-me 值替换成独立强密钥/密码，并填写真实域名
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
make prod
```

生产 overlay 会：

- 先运行唯一的 `release` 任务完成 migration、静态文件收集和 Django check；
- `release` 成功后才启动 Web；
- 使用 MySQL 8.4 和带密码的 Redis；
- 不向宿主机暴露 Django 8000 或 MySQL 3306；
- 由 Nginx 暴露入口，TLS 应在可信反向代理/负载均衡器终止。

不得把 `.env` 提交到 Git。不得把 `.env.dist` 的示例密钥用于生产。

## 健康检查

- `/health/`：进程存活检查，不访问依赖。
- `/ready/`：验证签字数据库为 MySQL，并在配置 Redis 时验证缓存读写。

生产发布只有在 `/ready/` 返回 `status=ok` 且 `database_vendor=mysql` 后才可接流量。

## 备份与恢复

CI 使用真实 `mysqldump`/`mysql` 执行备份恢复演练。生产备份必须使用专用凭据、加密存储、保留策略和定期恢复演练；仅生成备份文件不算验收。

## 故障定位

```bash
docker compose ps
docker compose logs --tail=200 db redis web
docker compose exec -T db mysqladmin ping -h 127.0.0.1 -uhorilla_user -p
curl http://localhost:8000/health/
curl http://localhost:8000/ready/
```

常见问题：

- `requires MySQL`：检查 `DATABASE_URL` 或 `DB_ENGINE`，不能指向 SQLite/PostgreSQL。
- MySQL 未就绪：先看 `db` 健康检查和密码是否一致。
- Redis 未就绪：检查 `REDIS_PASSWORD` 与 `REDIS_URL` 是否一致。
- 生产配置拒绝启动：这是 fail-closed；修正弱密钥、`DEBUG`、域名或可信来源，禁止关闭安全门禁。
