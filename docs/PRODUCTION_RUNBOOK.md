# 跃科高校人事系统生产运行手册

本手册是生产上线、日常值守、备份恢复和故障演练的唯一简版操作入口。生产签字数据库固定为 MySQL 8.4，缓存与任务协调固定为带密码的 Redis 7。

## 1. 上线前必须准备

1. 安装 Docker Engine/Desktop 与 Compose v2，并准备可信 HTTPS 域名和证书终止层；正式全栈（Web、MySQL、Redis、ClamAV 与全部 worker）建议从 8 GiB 内存起步，并保证至少 2 GiB 峰值余量。默认 3 个 Gunicorn worker，扩容前必须压测并记录峰值 RSS。
2. 从 `.env.dist` 复制 `.env`，逐项替换所有 `change-me`；`.env` 禁止提交 Git。
3. `BACKUP_STORAGE_PATH` 指向宿主机持久目录，容器运行用户（UID 1000）必须可写；该目录还必须异机复制。
4. 在 `REQUIRED_EXTERNAL_INTEGRATIONS` 中列出本校上线范围真正依赖的边界，可选值为 `HR08_IAM`、`HR08_ACADEMIC`、`HR15_PAYMENT`、`HR16_IAM`、`HR16_ASSET`、`HR16_FINANCE`、`HR18_SUBMISSION`、`HR18_EXCHANGE`。被声明的边界缺少 HTTPS 地址、令牌或可信回执密钥时，生产进程会拒绝启动。启用外聘教师门户或教务排课时，必须同时声明并联调 `HR08_IAM` 与 `HR08_ACADEMIC`。
5. MySQL 必须允许 migration 用户安装仓库内的确定性 trigger；Web 日常账号不得授予 `SUPER`。
6. 配置学校 SMTP 中继的 `EMAIL_HOST`、端口、账号、密码和真实发件地址。生产环境强制启用邮件双因素认证；本机、示例域名、静默丢信、同时开启 TLS/SSL 或完全不加密都会被启动门禁拒绝。
7. 单独生成数据库字段加密密钥并写入密钥系统，禁止与 Django、Redis 或备份密钥复用：

```bash
python -c "from cryptography.fernet import Fernet; print('primary:'+Fernet.generate_key().decode())"
```

将输出完整写入 `FIELD_ENCRYPTION_KEYS`。轮换时先把新密钥放在第一位并保留旧密钥，例如 `2027:new-key,2026:old-key`；完成凭据重加密和校验后才能移除旧密钥。缺失、格式错误或无法解密现存密文时生产进程会拒绝启动/读取，禁止回退成明文。

每个密码、Django `SECRET_KEY`、Redis 密码和备份加密密钥必须独立随机生成。不得在工单、聊天、日志或截图中暴露明文。

## 2. 发布与启动

在仓库根目录执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

`release` 是唯一迁移所有者，会依次迁移、收集静态文件并运行包含 Django deployment checks 的检查。只有它成功后 Web 与后台任务才启动。任何服务不是 `healthy` 时不得接入流量。

Python、MySQL、Redis、Nginx 和 ClamAV 均以不可变 SHA-256 镜像摘要固定；Dependabot 每周提出升级。摘要升级必须重新通过镜像漏洞扫描、Compose 解析、release、全量回归和本节验收，禁止在生产机直接把固定摘要改回漂移标签。

反向代理必须只把公网流量转发到 Nginx，传递 `X-Forwarded-Proto=https`，不得暴露 Web 8000、MySQL 3306、Redis 6379 或 ClamAV 3310。

## 3. 上线验收

```bash
curl -fsS https://真实域名/health/
curl -fsS https://真实域名/ready/
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 web
```

- `/health/` 只证明进程存活，数据库中断时仍应返回 200。
- `/ready/` 必须返回 `status=ok`、`database_vendor=mysql`、`cache=ok` 和 `malware_scanner=ok`，否则负载均衡器不得送流量。
- `hr18-submission-worker`、`hr18-exchange-worker`、`legacy-scheduler`、`employee-scheduler`、`backup-scheduler` 都必须为 `healthy`。健康检查使用 Redis 心跳，不依赖缓慢的 Django 启动。
- 登录管理员并人工走通：首页、组织岗位、人员主档、招聘入职、异动合同、考勤请假、考核、薪酬、离校和数据中心的本校关键路径。
- 外聘人员至少验收一次“聘用激活 → 门户授权入队并回执 → 绑定教务任务后教务身份生效 → 聘期到期/退出后权限和教务身份回收”。后台请求只能在真实回执后显示成功，重试耗尽必须产生重大风险记录。
- 用真实管理员邮箱请求一次登录验证码，确认 5 分钟内送达、错误验证码最多尝试 5 次、60 秒内无法重复发送；邮件失败时系统必须拒绝继续登录，不能绕过验证。

日志为 stdout JSON；以响应头和日志字段 `request_id` 串联一次请求。日志不得出现数据库密码、Bearer token、Cookie、备份密钥或完整身份证件数据。

## 4. 备份、校验与异机保存

生产 `backup-scheduler` 默认每 24 小时创建一次 AES-256-GCM 加密的 MySQL + media 包，保留数由 `PRODUCTION_BACKUP_RETENTION_COUNT` 控制且永不低于 2。手工创建和校验：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backup-scheduler python manage.py create_production_backup
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backup-scheduler python manage.py verify_production_backup 备份包目录名
```

每天检查最近一次备份时间、包大小和校验结果。宿主机备份目录必须按基础设施策略复制到不同故障域；本仓库不会假装本机目录等于异地灾备。备份加密密钥必须进入独立密钥管理系统，丢失后备份不可恢复。

## 5. 恢复演练

恢复必须使用名称不同的、预先创建的空数据库。命令会拒绝覆盖当前运行数据库，`--confirm-target` 还必须与目标名完全一致：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T \
  -e RESTORE_DATABASE_USER=恢复专用账号 \
  -e RESTORE_DATABASE_PASSWORD=恢复专用密码 \
  -e RESTORE_DATABASE_HOST=db \
  backup-scheduler python manage.py restore_production_backup 备份包目录名 \
  --target-database renshi_restore_drill \
  --confirm-target renshi_restore_drill
```

恢复后至少核对：迁移数量、核心表数量、抽样人员/组织/招聘/薪酬事实、media 文件可读性，以及用恢复库启动隔离 Web 后 `/ready/` 正常。每季度和每次大版本上线前执行一次，并记录 RPO、RTO、备份包名、校验哈希、恢复目标及验收人。演练完成后再由 DBA 按变更流程删除隔离恢复库。

## 6. 故障处置

先看状态和最近日志：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=300 db redis web hr18-submission-worker hr18-exchange-worker legacy-scheduler employee-scheduler backup-scheduler
```

- `/health/` 失败：Web 进程或反向代理故障，先摘流量再重启对应服务。
- `/health/` 正常而 `/ready/` 失败：数据库、Redis 或 ClamAV 故障，保留 Web 进程用于诊断，但继续摘流量；扫描器不可用时系统会以 503 拒绝所有文件上传，禁止绕过扫描直接写入材料目录。
- worker `unhealthy`：检查 Redis、依赖系统、租约/重试日志和心跳；不得手工把失败任务改成成功。
- 登录返回 429：等待 `Retry-After`，确认是否真实攻击或误输；禁止直接关闭限流。
- 生产启动被安全门禁拒绝：修正配置，禁止通过改代码、开启 `DEBUG` 或移除门禁绕过。

数据库、Redis 和各服务均设置 `restart: unless-stopped`，宿主机或 Docker 重启后仍需重新核对全部健康状态。

## 7. 发布回滚

应用回滚只能回到与当前数据库迁移向后兼容的已签字镜像。若版本包含不可逆迁移，先停止发布并按备份恢复流程在隔离环境验证，禁止直接对生产执行 `migrate app zero`、手工删列或覆盖当前数据库。代码回滚后重新执行本手册第 2、3 节的发布和验收步骤。

## 8. 上线签字清单

- [ ] 生产 Compose 解析、构建、release 全部成功
- [ ] Django production deployment check 无未处理问题
- [ ] `/health/`、`/ready/` 与所有 worker 均健康
- [ ] 使用无害文件和 EICAR 标准测试串分别验证上传放行与恶意文件拦截
- [ ] TLS、域名、反向代理、Cookie/CSRF 配置验收通过
- [ ] 学校 SMTP 真实投递通过，邮件双因素认证的过期、重发限流、错误次数锁定和发送失败关闭均验收通过
- [ ] 数据库凭据字段均为认证密文，`FIELD_ENCRYPTION_KEYS` 已进入密钥系统并完成一次保留旧密钥的轮换演练
- [ ] 本校必需外部边界已声明且真实联调通过
- [ ] HR08 IAM/教务可靠队列、幂等回执、失败重试和到期回收已联调通过
- [ ] 管理员最小权限、租户隔离和登录限流验证通过
- [ ] 首个加密备份已生成、校验并完成异机复制
- [ ] 独立恢复演练通过并记录 RPO/RTO
- [ ] HR01～HR18 关键业务人工验收通过
- [ ] 监控告警、值班人、DBA 与安全联系人已明确
