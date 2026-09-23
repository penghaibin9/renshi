# 跃科高校人事 V16 配置中心 + Integration Hub V1.1 实施门施工报告

## 1. 本轮定位

唯一连续基线：`Yueke_University_HR_V16_ConfigHub_IntegrationHub_V1_20260923`。

本轮**不新增 HR19/HR20，不改 HR01～HR18 业务事实，不扩菜单**。目标只做一件事：把上一版已经完成的“高校人事配置中心 V1 + Integration Hub V1”进一步收口为一条每个学校都可以重复执行的实施验收链：

`MySQL 8.4 migrate → 初始化 8 条草稿 → 浏览器配置 HR05 → 发布 → 建主数据连接 → 字段映射 → 实际 HTTP 连通性 → 数据库反查 → 实施门 PASS`

## 2. 新增施工内容

相对上一版 V1，本轮仅新增 6 个文件，没有修改 HR01～HR18 或原 V1 业务代码：

1. `.github/workflows/hr-config-integration-v1.yml`
   - MySQL `8.4` service；
   - 真实 `manage.py migrate` / `migrate --check` / `makemigrations --check`；
   - 建立一所验收学校和真实管理员；
   - 同一学校连续初始化两次，第二次必须 `created workflows=0`；
   - 启动真实 Django + 本地学校模拟接口；
   - `/ready/` 必须明确返回 `database_vendor=mysql`；
   - Playwright 使用正式 `/login/` 登录；
   - 浏览器完成配置、发布、Integration 建连、字段映射和“测试连接”；
   - 数据库反查后运行学校实施门。

2. `scripts/hr_config_integration_browser.py`
   - 不直接插数据库配置行；
   - 浏览器新增字段、审批角色、条件、通知、打印模板、Excel 模板/列；
   - 发布 HR05 配置；
   - 浏览器创建 `MASTERDATA_HTTP_JSON` 连接；
   - 浏览器创建 `employeeNo -> STAFF_NO` 映射；
   - 浏览器点击“测试连接”；
   - 检查配置哈希、Integration 合同哈希及密钥不泄漏。

3. `scripts/hr_config_integration_mock_school.py`
   - 仅作为专项验收用的学校侧 HTTP endpoint；
   - `/health` 返回真实 HTTP 200；
   - 不冒充某所学校正式接口。

4. `scripts/verify_hr_config_integration_v1.py`
   - 从数据库反查 8 条骨架、HR05 PUBLISHED、64 位发布哈希；
   - 反查字段/审批/条件/通知/打印/Excel；
   - 反查 `MASTERDATA_CI=VERIFIED`；
   - 确认密钥为 ciphertext，不含明文；
   - 反查字段映射和 `contractHash`。

5. `backend/hr_configuration/management/commands/hr_config_integration_v1_gate.py`
   - 以后每个学校都可以重复使用的正式实施门；
   - 强制数据库必须是 MySQL；
   - 强制版本必须是 MySQL `8.4.x`；
   - 强制两套 V1 migration 已应用；
   - 强制 8 条配置骨架存在且不重复；
   - 可按参数要求某个 HR 域已发布；
   - 可要求某类 Integration 已 VERIFIED；
   - 可要求至少存在一条字段映射；
   - 支持输出 JSON 实施证据。

6. `tests/configuration_hub/test_v1_acceptance_contract.py`
   - 防止以后把 MySQL 8.4 门降级成 SQLite；
   - 防止浏览器验收退化成直接写数据库；
   - 防止 Integration 测试绕过 host allowlist；
   - 防止密钥出现在合同；
   - 防止专项施工侵入 HR01～HR18。

## 3. 当前环境真实执行结果

已经实际执行并通过：

- 新增脚本/管理命令 `py_compile`：PASS；
- V1 源码合同 + 新专项合同：**12 passed**；
- `hr_configuration.tests + hr_integration.tests`：**11 tests / OK**；
- `makemigrations hr_configuration hr_integration --check --dry-run`：**No changes detected**；
- RepoClean 前端边界审计：**pass=true**；旧 `index.html` 父模板数量 **0**；旧组件引用 **0**；旧 UI 硬链接 **0**；
- Integration Hub 对 `127.0.0.1:9011/health` 做了真实 HTTP 请求：**VERIFIED / HTTP 200**；
- GitHub Actions YAML 解析：PASS。

## 4. 没有冒充完成的部分

当前施工容器没有 `mysql`、`mysqld`、Docker 或 Podman；用户远程电脑连接当前也是离线状态。因此本轮**没有声称 MySQL 8.4 + Playwright 整链已经在本机真实跑绿**。

这部分已经被固化为仓库内的 `HR Configuration + Integration V1 MySQL Browser Gate`。只要把本包合入 GitHub 分支或放到有 MySQL 8.4 的目标机，即可执行同一条链，不再靠人工记步骤。

正式学校实施后建议最后执行：

```bash
python manage.py hr_config_integration_v1_gate \
  --tenant <学校tenant_id> \
  --require-published HR05 \
  --require-verified MASTER_DATA \
  --require-mapping \
  --json-output implementation-gate.json
```

出现 `PASS` 才表示该校 V1 配置/集成实施门满足当前验收条件。

## 5. Linux 封包修复

上一版完整 ZIP 中有 2 个历史 docs 文件的单个文件名超过 Linux 常见 255-byte component 限制，直接 `unzip` 会出现 `File name too long`。

本轮 V1.1 完整包重新从上一版完整包构建：

- 业务源码、迁移和历史 docs 均保留；
- 仅对超长的 2 个历史文档文件名做安全短名替换；
- 包内 `docs/LEGACY_FILENAME_MAP_20260923.txt` 保存原文件名 → 安全文件名映射；
- 缓存目录、`.pyc`、`.pytest_cache` 不进入交付包。

因此 V1.1 可以作为比上一版更适合 Linux/MySQL 服务器展开的连续施工包。

## 6. 结论

本轮不是新增业务功能，而是把 V1 从“代码功能存在”推进到“有可重复实施门”。下一次换学校时，正常目标应该是：

**换学校配置 + Adapter + 字段映射，然后跑同一实施门；不修改 HR01～HR18。**
