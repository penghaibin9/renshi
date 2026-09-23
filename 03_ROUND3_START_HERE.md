# 跃科高校人事系统：第三轮接手入口（2026-09-15）

本包直接基于 `Yueke_University_HR_Round2_20260914.zip` 继续施工，不是说明包、补丁包或另建系统。基线 ZIP 已按随包 SHA256 核验：

`3538843133d0a4565f86bf30dce14dfcc3323d797d5ec8bf7539a634ecd440fa`

## 本轮已经实际改入源码

1. **生产 release 修正**：`docker-compose.prod.yml` 的 `release` 不再用 Compose 覆盖镜像入口脚本；保留 `/entrypoint.sh` 的数据库可达性和生产密钥门禁，再以固定 argv 执行 `python manage.py prepare_runtime --migrate --collectstatic`。Web/worker 仍等待 release 成功。
2. **生产 Compose 预检**：新增 `scripts/check_prod_compose.py` 和 `make prod-preflight`，要求 Docker Compose >= 2.24.4，并在启动前解析基础 Compose + 生产 overlay。
3. **首次部署初始化收口**：生产环境继续关闭网页初始化；过去可伪造 HX 头直达的子初始化 URL 现在还要求 DEBUG 且必须持有短期初始化会话授权；演示库装载入口生产环境直接 404，初始化口令比较改用 constant-time compare。
4. **首个学校/管理员安全初始化**：新增 `bootstrap_production_admin`。只接受全新库或完全一致的幂等重跑；首管密码仅从临时环境变量 `HR_BOOTSTRAP_ADMIN_PASSWORD` 读取，不接受 `--password` 参数；学校、超级管理员、Employee、WorkInformation 在一个事务中创建并关联。
5. **HR16 延迟退休终止改期**：批准的 `END_DELAY` 继任申请可复用原离校单；原单处于 SUBMITTED/APPROVED（或尚无任何交接事项的 HANDOVER）时受控退回 RETURNED，清除旧的访问终止时间并重新走复核/批准；旧状态、旧日期和新日期写入不可变的 HR16 申请事件。已有交接事项、结算或 effect 记录时拒绝自动改期，不覆盖既成事实。

## 当前真实验证结果

- 执行器最小文件写入/读回：**通过**。
- Round2 独立 Python 规则/契约：**66/66 通过**。
- Round3 新增生产部署/初始化/HR16 源码契约：**6/6 通过**。
- 后端 Python AST：**3076 文件通过**。
- `docker-compose.yml` / `docker-compose.prod.yml` YAML 语法解析：**通过**。
- `deploy/docker/entrypoint.sh` Bash 语法：**通过**。
- `backend + scripts + tests` compileall：**通过**。
- 新增 Django/MySQL 集成测试：首管初始化 6 项、HR16 受控改期 2 项，**源码已写入且 py_compile 通过，但当前云执行器不能运行**。
- 当前执行器缺：`django`、`rest_framework`、`MySQLdb`、Docker、MySQL client/server；因此真实 `docker compose config`、migration、MySQL trigger、Django 全量回归和浏览器流程仍不能在本轮云环境执行。没有用 SQLite 代替，也没有把“测试源码存在”写成“测试已通过”。

证据：`docs/reports/round3_evidence/`。
详细裁决：`docs/reports/HR_ROUND3_ENGINEERING_REPORT_2026-09-15.md`。

## 生产部署的正确顺序

先读 `docs/PRODUCTION_RUNBOOK.md`。正式环境不要重新打开网页初始化入口。最小顺序为：

```text
make prod-preflight
构建并启动生产 Compose（release 必须先成功）
对全新库执行一次 bootstrap_production_admin
清除 HR_BOOTSTRAP_ADMIN_PASSWORD 临时环境变量
检查 /health/、/ready/、worker、MFA
跑 HR01～HR18 MySQL 回归与真实角色业务验收
备份 + 恢复演练后再签字放行
```

当前包仍标记 **NOT_RELEASED**，原因是目标 MySQL/Docker/浏览器环境的运行验收尚未在本执行器完成，不是因为本轮源码没有改动。
