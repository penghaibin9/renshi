# 跃科高校人事系统：Round10 高校采购级验收参考与 HR18 接口同步收口入口（2026-09-16）

唯一基线：`Yueke_University_HR_Round9_20260916.zip`  
外部参考：用户提供的 9 页《一站式非学历教育智慧前台建设项目采购清单》。

> 参考文件只用于发现“真实高校采购会验什么”，**不改变 HR01～HR18 模块边界，不把非学历教育业务照搬进人事系统**。

## 本轮已完成

1. HR18 exchange workbench 增加当前字段映射和同步健康：待处理、已传输、已对账、待人工处理、历史最终失败、最近状态、最近错误和最近成功时间。
2. 根据 `expectedReceipt` 明确成功语义：需要回执的目标必须 `RECONCILED` 才算端到端成功；不需要回执的目标以 `TRANSMITTED` 为成功。
3. 最终失败支持单条人工重试和最多 100 条批量重试。
4. 人工重试**不重置原失败 Job**，而是创建 `retry_of_job` successor；原 attempts/dead-letter 历史保留。
5. 人工重试增加操作人、原因和精确幂等校验；同一幂等键改原因/编号/重试次数时 fail-closed。
6. dead-letter 的“历史失败”与“当前仍需人工处理”分离，避免成功重试后工作台仍误报为待处理。
7. 新增 migration `hr_data/0019_exchange_manual_retry_provenance.py`。
8. 新增采购性能 QA probe：默认普通页面 3 秒、复杂统计 5 秒、100 并发；只 GET，且必须显式 `--allow-load` 才运行。
9. 新增 Round10 静态门和纯源码回归。

## 关键文件

- `backend/hr_data/models.py`
- `backend/hr_data/services/exchange_service.py`
- `backend/hr_data/exchange_api.py`
- `backend/hr_data/api_urls.py`
- `backend/hr_data/migrations/0019_exchange_manual_retry_provenance.py`
- `frontend/static/hr/js/pages/hr18-actions.js`
- `backend/hr_data/tests/test_exchange_service.py`
- `backend/hr_data/tests/test_exchange_api.py`
- `scripts/check_hr18_procurement_sync_contract.py`
- `scripts/run_procurement_performance_probe.py`
- `tests/round10/test_procurement_sync_contract.py`
- `docs/reports/HR_ROUND10_PROCUREMENT_REFERENCE_CLOSURE_2026-09-16.md`

## 本轮静态门

```bash
python scripts/check_hr18_procurement_sync_contract.py
python -m unittest discover -s tests/round10 -p 'test_*.py' -v
node --check frontend/static/hr/js/pages/hr18-actions.js
```

## 当前静态复验

- Round2～Round10 纯源码：169/169 PASS；
- HR10 import gate：20/20 PASS；
- HR10 staff identity gate：53/53 PASS；
- HR18 procurement sync gate：24/24 PASS；
- 全仓 Python AST：3,148 文件，0 错误；
- JavaScript `node --check`：253 文件，0 错误。

当前执行器没有 Django，不能把上述静态门当成 MySQL 动态验收。

## QA 环境必须补跑

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py migrate --check
python manage.py test \
  hr_data.tests.test_exchange_service \
  hr_data.tests.test_exchange_api -v 2
```

并做真实：双管理员并发人工重试、provider 失败/恢复、回执/对账、浏览器操作、脱敏数据 100 并发及 3s/5s 性能门。

当前状态：**SOURCE_CODE_CANDIDATE / NOT_RELEASED**。
