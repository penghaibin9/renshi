# 跃科高校人事系统生产运行手册

本手册是生产上线、日常值守、备份恢复和故障演练的唯一简版操作入口。生产签字数据库固定为 MySQL 8.4，缓存与任务协调固定为带密码的 Redis 7。

## 1. 上线前必须准备

1. 安装 Docker Engine/Desktop 与 **Docker Compose v2.24.4 或更高版本**（生产 overlay 使用 `!override`），并准备可信 HTTPS 域名和证书终止层；正式全栈（Web、MySQL、Redis、ClamAV 与全部 worker）建议从 8 GiB 内存起步，并保证至少 2 GiB 峰值余量。默认 3 个 Gunicorn worker，扩容前必须压测并记录峰值 RSS。
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

另外独立生成至少 32 字节随机值写入 `FIELD_FINGERPRINT_KEY` 与 `HR08_TICKET_SIGNING_KEY`。生产启动门禁会拒绝它们与 `SECRET_KEY`、备份密钥、字段 Fernet 密钥互相复用。可检索身份证件/证书号使用租户级 HMAC 指纹，HR08 短时下载票据使用独立 HMAC 密钥。

如果数据库来自 Round6 或更早版本，**接入真实流量前**执行一次敏感字段升级审计：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm web \
  python manage.py rotate_hr_field_security --tenant 真实租户ID

# 确认审计输出后才允许写入；执行完成必须再次 --check 为 0
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm web \
  python manage.py rotate_hr_field_security --tenant 真实租户ID --apply
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm web \
  python manage.py rotate_hr_field_security --tenant 真实租户ID --check
```

该命令会升级 HR03 证件、HR05 银行信息、HR09 证书号，以及有可解密原文的 HR04 候选人证件。Round6 及更早的 HR04 只保存不可逆 hash、没有密文原文的记录会以 `hr04_hash_only_unresolved` 阻断；这些记录必须由有权限的人重新核验/录入证件号，或在确认仅为演示数据时按数据治理流程清理，禁止猜测原证件号。

每个密码、Django `SECRET_KEY`、Redis 密码和备份加密密钥必须独立随机生成。不得在工单、聊天、日志或截图中暴露明文。

### 1.1 先跑隔离生产形态验收，不要直接拿正式库试错

第四轮新增独立验收门禁。它**不会读取正式 `.env`，不会连接生产数据库，也不会部署生产服务**；脚本会生成一次性随机密钥，使用包含 `acceptance` 的独立 Compose project/volume，完成后自动销毁。上线候选代码应先执行：

```bash
make acceptance-plan
make acceptance-qa
```

`make acceptance-qa` 会依次验证：Compose >= 2.24.4、生产 overlay 合并、当前源码镜像构建、MySQL 8.4/Redis/ClamAV、release migration/collectstatic、`check --deploy`、迁移漂移、敏感字段密钥升级状态、HR01～HR18 Django/MySQL 测试、全新库首管初始化、加密备份、备份校验、恢复到单独数据库、恢复库 migration check、原库/恢复库表数量一致，以及容器内 `/ready/` HTTP 200。

安全边界：

- project 名含 `prod` / `production` / `live` 时脚本直接拒绝；
- project 名不含 `acceptance` 或 `qa` 时脚本直接拒绝；
- 正式 `make prod` 不加载 `docker-compose.acceptance.yml`；
- 验收环境的数据库、Redis、备份目录和管理员密码全部为临时随机值；
- 默认结束即 `down -v`，不会保留测试卷；只有显式 `--keep` 才留作故障诊断；
- 该门禁通过仍不代替目标学校的 SMTP、IAM、银行/财税、电子签章等真实外部联调。

若运行主机没有 Docker，门禁必须返回失败，不得把源码静态检查冒充成生产验收。

### 1.2 正式开流量前再跑一次租户只读体检

`acceptance-qa` 证明候选代码能在隔离 MySQL 生产形态下运行；真实学校正式开流量前，还必须针对该校租户执行一次**只读**体检，不自动修数据、不切 Authority：

```bash
make go-live-audit TENANT_ID=真实租户ID
```

该体检会统一检查：字段加密/检索指纹/HR08 下载票据是否使用互不复用的生产密钥、旧敏感字段是否仍待 rewrap、HR01～HR18 Authority Gate、HR05 是否存在超过 15 分钟的卡死导入、HR03/HR05/HR06 是否存在 DEAD/DROPPED 事件，以及已有 HR09 正式资质数据时是否已经完成可审计的 Authority 切换。命令只读；出现 blocker 时必须先按对应业务流程修复，再重新执行，禁止为了“变绿”手工改数据库状态。

HR09 从旧资质数据切换到新 Authority 时必须先做双读对账，再带对账报告号切换，禁止使用无报告的强制切换：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm web \
  python manage.py hr09_switch_authority --tenant 真实租户ID \
  --mode DUAL_READ_COMPARE --reason "上线前双读对账" --cutover-by 运维账号

# 完成 dual compare / 归档对账结果后：
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm web \
  python manage.py hr09_switch_authority --tenant 真实租户ID \
  --mode HR09_AUTHORITY --reason "对账通过，切换正式权威源" \
  --cutover-by 运维账号 --verification-report-id HR09-真实对账报告号
```

HR05 Excel 导入在本版起使用数据库持久化 Job/Row 账本，不再依赖 Gunicorn 单进程内存；上传、校验、确认和错误表下载可以跨 worker/重启继续追踪。`confirm` 只把持久 Job 置为待执行并返回 HTTP 202，逐行提交由独立 `hr05-import-worker` 完成，Web 请求不再同步处理最多 5000 行。单文件上限 10 MiB、5000 行，同时在 openpyxl 解析前拒绝异常 XLSX 压缩膨胀包。缺必需表头、重复表头、只有表头无数据、ZIP 路径含 Windows 反斜杠/越界片段均直接拒绝。

## 2. 发布与启动

在仓库根目录执行：

```bash
make prod-preflight
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

`prod-preflight` 会先拒绝低于 v2.24.4 的 Compose，并真正解析两份 Compose 文件；解析失败不得继续部署。`release` 是唯一迁移所有者：它保留镜像 `/entrypoint.sh`，先执行数据库可达性与生产密钥检查，再用固定参数执行 `python manage.py prepare_runtime --migrate --collectstatic`。只有 release 成功后 Web 与后台任务才启动。任何服务不是 `healthy` 时不得接入流量。

### 2.1 全新数据库首次建校与首个管理员

生产环境的网页初始化入口必须保持关闭。首次 migration/release 成功后，使用一次性管理命令创建学校与首个管理员；管理员密码只通过临时环境变量传入，**不要**写入命令行参数、`.env`、工单或脚本：

```bash
read -s HR_BOOTSTRAP_ADMIN_PASSWORD
export HR_BOOTSTRAP_ADMIN_PASSWORD

docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm release \
  python manage.py bootstrap_production_admin \
  --username school_admin \
  --email admin@school.example \
  --first-name 系统管理员 \
  --phone 13800000000 \
  --company-name "示例大学（替换为真实校名）" \
  --company-address "真实地址" \
  --company-country "中国" \
  --company-state "湖南省" \
  --company-city "长沙市" \
  --company-zip 410000

unset HR_BOOTSTRAP_ADMIN_PASSWORD
```

命令只接受空库，或者“此前已经以完全相同参数成功执行”的幂等重跑；发现已有其他用户、教职工或学校数据时会拒绝继续，避免把新超级管理员误挂到已有业务数据。执行成功后立即用该账号登录并完成 MFA 验收。

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
- `hr05-outbox-worker`、`hr05-import-worker`、`hr18-submission-worker`、`hr18-exchange-worker`、`legacy-scheduler`、`employee-scheduler`、`backup-scheduler` 都必须为 `healthy`.健康检查使用 Redis 心跳，不依赖缓慢的 Django 启动。HR05 worker 是 Authority publication verifier，不得重复执行 HR03/HR02 生效写入。
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
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=300 db redis web hr05-outbox-worker hr05-import-worker hr18-submission-worker hr18-exchange-worker legacy-scheduler employee-scheduler backup-scheduler
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

- [ ] Docker Compose >= 2.24.4，`make prod-preflight`、构建、release 全部成功
- [ ] 全新库已通过 `bootstrap_production_admin` 一次性创建真实学校与首管，临时密码环境变量已清除；非新库不得执行
- [ ] Django production deployment check 无未处理问题
- [ ] `/health/`、`/ready/` 与所有 worker 均健康（含 `hr05-outbox-worker` / `hr05-import-worker`）
- [ ] `go-live-audit` 中 HR05 无超 15 分钟 PENDING/FAILED outbox，HR08 provisioning 无终态 FAILED，HR18 submission/exchange 无 DEAD/DEAD_LETTER
- [ ] 使用无害文件和 EICAR 标准测试串分别验证上传放行与恶意文件拦截
- [ ] TLS、域名、反向代理、Cookie/CSRF 配置验收通过
- [ ] 学校 SMTP 真实投递通过，邮件双因素认证的过期、重发限流、错误次数锁定和发送失败关闭均验收通过
- [ ] HR03/HR04/HR05/HR09 高敏字段均使用独立字段密钥；`FIELD_ENCRYPTION_KEYS`、`FIELD_FINGERPRINT_KEY`、`HR08_TICKET_SIGNING_KEY` 已进入密钥系统且互不复用
- [ ] `python manage.py rotate_hr_field_security --tenant 真实租户ID --check` 返回 0；Round6 旧 HR04 hash-only 记录已人工核验/重录或按治理流程清理
- [ ] `make go-live-audit TENANT_ID=真实租户ID` 在 `--strict` 模式返回 `READY_FOR_RUNTIME_ACCEPTANCE`，JSON 证据已归档
- [ ] HR05 Excel 导入真实验证：上传后重启/切换 Web worker 仍可查询 Job、确认导入、下载错误表；5000 行门槛和重复确认幂等通过
- [ ] 若本校已有 HR09 历史资质数据：双读对账完成，`HrAuthorityCutover` 已记录 `AUTHORITY_ONLY` 和真实 `verification_report_id`
- [ ] 对外报送/交换的全校教职工数据已按 JY/T 0661-2025 完成数据资产梳理、分类分级、校内审批/备案和动态更新责任人；全校范围最低 L3
- [ ] 本校必需外部边界已声明且真实联调通过
- [ ] HR08 IAM/教务可靠队列、幂等回执、失败重试和到期回收已联调通过
- [ ] 管理员最小权限、租户隔离和登录限流验证通过
- [ ] 首个加密备份已生成、校验并完成异机复制
- [ ] 独立恢复演练通过并记录 RPO/RTO
- [ ] HR01～HR18 关键业务人工验收通过
- [ ] 监控告警、值班人、DBA 与安全联系人已明确

## 9. 学校数据与系统资料移交（合同终止/更换供应商）

> 这条链路与第 4～5 节“日常加密灾备”不同。灾备包用于同系统灾难恢复；学校移交包用于采购验收、合同终止或更换供应商，必须保持开放格式、可核验、可在隔离新环境恢复，不能依赖跃科私有解密格式。

生产 Compose 将学校移交目录与审计回执目录分别挂载到 `/app/handover` 和 `/app/handover-audit`。宿主机 `.env` 必须配置：

```bash
HANDOVER_STORAGE_PATH=/srv/renshi/handover
HANDOVER_AUDIT_STORAGE_PATH=/srv/renshi/handover-audit
```

两个目录必须位于 Web 静态目录、媒体公开目录和前端目录之外，只允许受权运维人员访问。移交包包含完整人事数据库和附件，属于高敏资产。

正式移交必须安排经审批的维护/写入冻结窗口：`mysqldump --single-transaction` 能保证事务型表的数据库快照一致性，但数据库与媒体文件系统不是一个分布式事务；如果导出期间仍允许上传附件或变更业务配置，数据库引用与文件快照可能跨时点。当前命令不会冒充能够证明外部流量已经冻结，运维验收清单必须保留该人工/环境前置条件。

### 9.1 生成开放格式学校移交包

必须显式提供接收方、用途、操作人，并输入固定确认词。命令拒绝静默导出：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T \
  backup-scheduler python manage.py create_school_handover_package \
  --recipient "学校信息中心/档案管理部门" \
  --purpose "合同到期数据移交" \
  --operator "经授权运维人员" \
  --confirm-sensitive-export I_UNDERSTAND_THIS_EXPORT_CONTAINS_SENSITIVE_HR_DATA
```

生成结果包括标准 `.tar.gz` 和同名 `.sha256` 侧车校验文件；两者必须一起交付。`.sha256` 会在校验和恢复前强制核对，包字节发生变化时拒绝继续。移交包内部至少包含：

- `database.sql`：标准 MySQL 逻辑 SQL；
- `media.tar.gz`：附件/材料文件；
- `schema_dictionary.csv` / `schema_dictionary.json`：数据库字段字典；
- `table_row_counts.csv` / `table_row_counts.json`：`database.sql` 实际序列化行数台账，用于恢复完整性核验；
- `migration_state.json`：Django 迁移状态；
- `api_route_inventory.csv`：当前接口路由清单；
- `configuration_catalog.csv` / `configuration_catalog.json`：规则、配置、策略、周期、字段映射等配置表索引与行数；
- `interface_mapping_catalog.json`：HR18 对外交换目标的非密钥字段映射版本；
- `runtime_configuration.json`：不含密码/密钥的运行配置说明；
- `secret_handover_requirements.json`：只列必须单独交接/重签发的密钥类别和 Key ID，不包含密钥值；
- `delivery_docs/`：部署、权限、数据库兼容、Authority/Provider/对账等文档；
- `manifest.json`：所有文件的字节数与 SHA-256；
- `README-HANDOVER.txt`：接收与恢复说明。

`database.sql` 中已经存在的高敏字段可能仍是系统的标准 Fernet 密文。为了既不泄露密钥、也不制造供应商锁定，**FIELD_ENCRYPTION_KEYS 必须通过学校控制的独立安全通道单独交接**；包内只记录 Key ID，不记录密钥值。`FIELD_FINGERPRINT_KEY` 必须单独交接或在新系统完成受控重建。`SECRET_KEY`、短时票据签名密钥和第三方账号密码应在新环境重签发/轮换，而不是塞进数据包。

源代码按合同要求使用与该数据库版本匹配的签字源码发布包单独交付；运行密钥不得打进源码包。

### 9.2 校验移交包

交付前和接收后都必须执行同一校验：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T \
  backup-scheduler python manage.py verify_school_handover_package \
  学校移交包.tar.gz \
  --operator "校验人员"
```

校验会拒绝路径穿越、符号链接/设备文件、未登记文件、缺文件、大小变化和 SHA-256 不一致。校验与恢复动作写入独立 JSONL 审计回执，不改写原导出回执。

### 9.3 在隔离新环境做恢复验收

恢复**只能进入名称不同的、预先创建的空数据库**，并要求二次输入完全一致的目标库名和固定恢复确认词。严禁覆盖当前生产数据库：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T \
  -e RESTORE_DATABASE_USER=恢复专用账号 \
  -e RESTORE_DATABASE_PASSWORD=恢复专用密码 \
  -e RESTORE_DATABASE_HOST=db \
  backup-scheduler python manage.py restore_school_handover_package \
  学校移交包.tar.gz \
  --target-database renshi_handover_acceptance \
  --confirm-target renshi_handover_acceptance \
  --media-target /app/.runtime/handover-media-acceptance \
  --operator "恢复验收人员" \
  --confirm-restore-policy RESTORE_TO_EMPTY_DATABASE_ONLY
```

恢复命令会先校验包，再检查目标库为空；恢复后自动比对表数量、`django_migrations` 数量，并逐表比对导出时记录的精确 `COUNT(*)`，防止“表都建出来了但业务数据只恢复了一部分”仍被误判为成功。MySQL DDL 无法保证整库事务回滚，如果 SQL 导入中途失败，**不得在半恢复库上继续重试**，必须删除该隔离目标库、重新创建空库后再执行。

最终移交验收至少还要人工核对：组织、人员主档、任职、合同、考勤请假、考核、薪酬、资质、培训实践、附件可读性、关键规则版本、接口字段映射，并使用恢复库启动隔离 Web 验证 `/ready/`。将包名、包 SHA-256、接收方、操作人、恢复目标库、验收时间和签字人归档。

### 9.4 不允许的做法

- 不允许把日常 AES 灾备包冒充学校移交包；
- 不允许只给 Excel 汇总而不交付数据库结构与完整业务数据；
- 不允许把密码、Token、字段密钥直接写进移交包或源码包；
- 不允许用私有二进制格式作为唯一数据载体；
- 不允许恢复到当前生产数据库；
- 不允许删除或覆盖导出/校验/恢复审计回执；
- 不允许在未完成隔离恢复验证前宣称“可迁移”。

## 10. 最终采购级验收证据包

源码通过静态门**不等于学校已经验收**。最终候选版将源码能控制的检查与必须由真实环境/人员/第三方提供的证据分开：

1. 在隔离 QA/学校预发布环境执行 `scripts/run_hr_acceptance_gate.py`，完成 MySQL migration、HR01～HR18 测试、学校初始化快照、灾备恢复、开放移交恢复和 `/ready/`。
2. 使用 `scripts/run_procurement_performance_probe.py --allow-load` 对采购人认可的脱敏真实数据执行代表性已登录页面测试；并发不少于 100，普通页面阈值不高于 3000ms，复杂统计阈值不高于 5000ms。
3. 按 `docs/qa/TRIAL_RUN_RECORD_TEMPLATE.json` 形成试运行记录，所有抽样流程必须 PASS，并记录采购人/供应商代表和双方确认。
4. 按 `docs/qa/REMEDIATION_REGISTER_TEMPLATE.csv` 关闭整改项；不得用空 CSV 冒充“无问题”，无问题时也要形成明确 `NO_ISSUES` 记录并由学校接受。
5. 按 `docs/qa/TRAINING_RECORD_TEMPLATE.csv` 至少完成 ADMIN、OPERATOR 两类人员培训并确认。
6. 按 `docs/qa/EXTERNAL_INTEGRATION_ACCEPTANCE_TEMPLATE.json` 对合同要求的学校统一认证、数据中台及其他外部平台逐项联调；真实条件缺失时必须保留 PENDING/NOT_APPLICABLE，不得用 mock 签发通过。
7. 最后运行 `scripts/build_procurement_acceptance_package.py`。只有输出 `COMPLETE` 且包内存在 `release_certificate.json` / `releaseCertificate=true`，才说明这六类证据通过机器检查；采购人的正式签章/验收流程仍以合同为准。

推荐一条总门命令：

```bash
python scripts/run_hr_acceptance_gate.py \
  --project yueke_hr_final_acceptance \
  --procurement-pack-output /secure/evidence/Yueke_HR_Final_Acceptance_Evidence.zip \
  --procurement-performance-json /secure/evidence/performance.json \
  --trial-run-record /secure/evidence/trial-run.json \
  --remediation-register /secure/evidence/remediation.csv \
  --training-record /secure/evidence/training.csv \
  --external-integration-record /secure/evidence/external-integrations.json
```

任何一项缺失时总门必须失败，不得人工把 `INCOMPLETE` 改成 `COMPLETE`。
