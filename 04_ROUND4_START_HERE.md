# 跃科高校人事系统：第四轮接手入口（2026-09-15）

第四轮只以 `Yueke_University_HR_Round3_20260915.zip` 为唯一基线继续施工，没有回退 Round2、没有连接 GitHub、没有访问生产服务器或生产数据库。

## 本轮实际收口的三条主线

### 1. HR16 弹性退休证据链从“有文件”收口到“材料用途可证明”

第三轮已经完成 END_DELAY 对已批准离校计划的受控改期；第四轮继续收紧审批证据：

- 人事材料新增四个独立分类：`RETIREMENT_NOTICE`、`RETIREMENT_APPROVAL`、`RETIREMENT_CONTRIBUTION`、`RETIREMENT_AGREEMENT`；
- 本人提交弹性退休时，书面告知必须引用 `RETIREMENT_NOTICE`；
- 人事审批时，审批依据、社保缴费核验材料、双方书面协议必须分别引用对应分类；
- 同一材料/同一文件版本不得在多个证据槽位重复使用；
- 审批核验记录落到**被审批时选中的那个不可变文件版本**，即使后来该材料上传了新版本，也不会把核验状态偷换到新版本；
- 审批封存快照保存类别、SHA256、文件版本、核验人和核验时间；
- HR16 管理端上传材料必须明确用途，HR17 本人端只把弹性退休书面告知放入对应类别选择器。

### 2. HR18 历史指标新增 HR07 正式合同权威事实

历史指标不再只覆盖 HR03/HR13/HR14/HR16。第四轮把 HR07 接到**正式合同版本**而不是草稿/办理单：

- `HrContractVersion` 的 EFFECTIVE / SUPERSEDED / TERMINATED / EXPIRED 历史有效区间可用于 as-of STAFF COUNT；
- 支持按 staff、employment relationship、agreement type、subject type、version type、effective dates、status 过滤；
- 同一合同在目标历史日期有两个正式版本重叠时，直接返回 `ASOF_EVALUATION_SOURCE_CONFLICT`，不偷偷挑一条；
- 历史证据哈希纳入 VOID、`supersedes_version_id` 和 `content_hash`，后续作废/更正会改变证据口径；
- HR18 质量 Provider 新增 `HR07_CONTRACT_VERSION_INTEGRITY`，检查跨租户挂接、正式版本缺签署证据、内容哈希非法、有效期非法、前后版本链异常、正式版本区间重叠。

HR04/HR05/HR06/HR12/HR15 仍保持 fail-closed。它们存在撤销、更正、继任链，第四轮没有为了增加“支持域数量”直接 COUNT 可变工作流表。

### 3. 生产验收由说明变成可执行隔离门禁

新增：

- `docker-compose.acceptance.yml`
- `scripts/run_hr_acceptance_gate.py`
- `make acceptance-plan`
- `make acceptance-qa`

门禁只允许独立 acceptance/qa Compose project，拒绝 prod/production/live 命名；不读取正式 `.env`，自动生成临时随机密钥和独立 MySQL/Redis/备份卷。首管密码不落共享 env，只在首管命令单次容器中临时注入。真实有 Docker 的 QA 主机上，它会自动执行：

1. Compose 版本与配置合并；
2. 当前源码镜像构建；
3. MySQL 8.4 + Redis + ClamAV；
4. production release；
5. `check --deploy`、迁移漂移检查、`migrate --check`；
6. HR01～HR18 Django/MySQL 测试；
7. 全新库 `bootstrap_production_admin`；
8. 加密备份与备份解密校验；
9. 恢复到单独 `renshi_restore_test` 数据库；
10. 恢复库 migration check + 原库/恢复库表数量核对；
11. 启动 web 并在容器内验证 `/ready/` HTTP 200；
12. 默认销毁该验收 project 和 volumes。

当前 ChatGPT 云执行器实测没有 Docker、没有 Django，因此本轮真正运行该门禁时在第一步 `docker compose version` 立即 fail-closed，没有长时间空转，也没有把失败改成绿灯。

## 当前可执行验证

- Round2 纯契约：66/66 PASS
- Round3 纯契约：6/6 PASS
- Round4 纯契约/验收门禁安全测试：16/16 PASS
- Round4 acceptance `--plan`：PASS
- acceptance 真执行：BLOCKED / fail-closed（当前执行器没有 Docker）
- Django/MySQL 集成测试源码：已继续增加和修正，但当前执行器缺 Django/MySQL，不能声称已运行

详细证据与剩余边界见：

`docs/reports/HR_ROUND4_CLOSURE_REPORT_2026-09-15.md`

当前源码仍标记 **NOT_RELEASED**。第四轮把阻断进一步收缩到“目标 Docker/MySQL/真实外部接口/真实浏览器角色验收”，而不是继续留着已知的 HR16 证据混用或 HR07 历史指标假算问题。
