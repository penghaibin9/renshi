# P0/P1/P2 操作与执行边界

## 1. 输入与输出

连续基线是V10，SHA256 `00a02389b462ecc53b3f14ff8e4257d9f1e7f53ad998899538d370f508839dad`。本次差异仅用于这个基线。有并行改动先合并，不用整包覆盖。

原生产Dockerfile、requirements.lock、docker-compose.yml、docker-compose.prod.yml不改。脚本使用原Python3.12镜像、锁定依赖、MySQL8.4固定摘要、Redis、ClamAV、原release迁移与静态资源命令。

## 2. 默认只读诊断

在解压源码根目录执行：

```sh
python scripts/run_hr_p012_gate.py
```

不安装软件、不读取部署`.env`、不启动数据库。缺Docker时退出2；宿主工具存在但没有执行容器时退出3。生成唯一JSON报告；宿主依赖匹配情况不等于镜像依赖匹配情况。

可以用`--report 路径.json`指定一个尚不存在的文件。拒绝覆盖旧证据，拒绝把报告写入`.env`。JSON不包含数据库口令、密钥或人员记录。

## 3. 有隔离环境后执行

仅在授权的本地隔离Docker环境执行，不在生产部署目录操作：

```sh
python scripts/run_hr_p012_gate.py --execute
```

它为每次执行生成独立Compose项目、独立镜像标签、随机秘密及私有运行目录，拒绝远程Docker上下文、已有同名资源、宿主端口、外部数据卷和不在隔离路径内的可写挂载。九个应用服务的env_file均指向当次生成文件。

实际顺序：解析并验证Compose配置→构建原发布镜像→启动MySQL/Redis/ClamAV→原release完整迁移与collectstatic→镜像依赖锁一致性→原Django部署检查→模型与迁移检查→MySQL版本/模式/表引擎/关键触发器→只在新隔离库授予测试库权限→9项MySQL限定校本配置测试→启动web→容器内ready检查。

任一步失败立即停止后续阶段，记录BLOCKED；未开始的阶段保持NOT_EXECUTED。仅清理本次拥有的资源，不清理其他QA/生产项目。`--keep`只为保留本次隔离故障现场；密码文件及数据卷应由授权人员保密管理。

不自动执行人员导入、正式起薪、工资重算、银行支付、备份恢复、完整业务迁移等P3–P7内容。原广域`run_hr_acceptance_gate.py`仍保留，但不是本轮P012执行入口。

## 4. 不能被自动结果替代的验收

即使上述技术阶段都通过，脚本仍返回非零3，状态TECHNICAL_GATES_PASSED_PENDING_ACCEPTANCE，不批准交付。还需：

- 独立TLS入口、实际用户名密码、原邮件双因素或SSO；不得关闭MFA来取得登录成功。默认生成的SMTP占位地址不提供真实邮件能力。
- 全局原生导航、静态资源、Cookie/CSRF，以及真实校级/院系/本人/跨校权限和私有文件。容器内部ready带代理头检查不算TLS浏览器验收。
- 原完整迁移图在新空隔离库通过，与带历史业务数据的升级演练是两件事；后者仍需单独授权样本及对账证据。
- Windows125%、实际文件选择器及校方签认等后续门禁保持未验证。本轮不进入P3–P7。

## 5. 已有只读预检

在已建立完整真实运行环境后，使用原命令：

```sh
python manage.py hr_first_delivery_check --tenant-id <实际学校ID> --report .runtime/first-delivery.json
```

要求原完整设置、18个HR应用、学校权限、租户中间件顺序、MFA/扫描/安全Cookie、原迁移图及真实学校。只读查询，不建表、不授予权限、不修数据。返回BLOCKED退出2或NEEDS_ACCEPTANCE退出3；不能以此命令代替浏览器或校方验收。

## 6. 升级与回退

本轮无新迁移、无业务数据变更。可在没有并行冲突时应用本次PATCH；恢复V10的这几个验收文件不会回滚业务数据。验收工具创建的新隔离数据只属于其独立QA项目，不能从真实生产库恢复或覆盖过去。

原V10/P1方案发布、绑定等正式事实仍遵守旧规则；不得为运行旧版而删除它们，也不得跳过0018及更早迁移。保留原LICENSE及所有版权信息，不添加系统字体或离线Python依赖到产品包。
