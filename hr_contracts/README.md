# HR07 合同管理

这是 HR07 的模块入口。当前仓库里的 HR07 代码历史上存在缺失，重构时以 GitHub 当前代码、最高设计合同和可验证业务链为准重新恢复，不以旧 READY 文档作为完成证据。

## 小白先看这里

目标目录统一为：

- `models/`：合同、版本、续签/变更/终止等正式事实。
- `services/`：合同写操作和状态机。
- `selectors/`：合同列表、到期预警和历史查询。
- `api/`：正式 API。
- `jobs/`：提醒、导出等异步任务。
- `policies/` / `permissions.py`：规则、角色、数据范围。
- `templates/` / `views/`：管理端页面。
- `tests/`：合同生命周期、权限、租户、并发和历史测试。

## 重构硬规则

1. 先恢复权威模型和完整生命周期，再做 UI 美化。
2. 合同生效/终止事实不可被其他模块直接改表。
3. 历史版本必须可追溯，不能覆盖旧合同事实。
4. 到期提醒、导入导出必须可审计。
5. 正式 API 统一 `/api/v1/hr/...`。

## 合同到期 worker

生产调度器只需要调用同一个显式入口，不得在 Web 请求或旧
`payroll.Contract` 上自行扫描：

```text
python manage.py hr07_scan_expiry --tenant-id <学校ID> --as-of YYYY-MM-DD --dry-run
python manage.py hr07_scan_expiry --tenant-id <学校ID> --as-of YYYY-MM-DD
```

每个学校必须先发布且只发布一个匹配合同类型的有效到期策略。策略缺失、
策略冲突、当前合同版本或签署证据不完整时，本次合同处理会明确阻断。命令
本身不包含定时器；部署环境应按学校逐一排程，并显式传入业务日期。
