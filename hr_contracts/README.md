# HR07 合同管理｜恢复中

> **当前状态：INCOMPLETE，禁止当成已经完成的 Django app 注册上线。**

当前仓库只保留了 `api/`、`services/`、`templates/`、`templatetags/`、`display_labels.py`、`metrics.py` 等残片；缺少可确认的 `apps.py`、完整模型入口、migration 历史和模块测试入口。因此本轮重构先保护现存可用代码并恢复事实链，不凭文档描述伪造数据库结构。

## 目标职责

HR07 最终只权威拥有合同主档、合同版本、签订/续签/变更/解除案例和合同有效期历史。人员主档属于 HR03，人事异动属于 HR06；跨域变化必须使用受控命令/事件。

## 新人怎么看这里

1. `module_contract.py`：先看模块边界和缺失项；
2. `api/`：现存接口残片，恢复前不得继续扩散新接口；
3. `services/`：现存业务服务，逐项确认引用后收编；
4. `templates/`：现存页面，按真实后端能力逐页验收；
5. `RECOVERY_CHECKLIST.md`：恢复到可注册 Django app 前必须完成的清单。

## 删除规则

任何旧文件只有同时满足“无 import / 无 URL / 无模板引用 / 无设计合同要求 / 已有替代实现 / 回归测试通过”才允许删除。数据库表和 migration 绝不通过猜测重建或删除。
