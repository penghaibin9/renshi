# HR01 人事工作台

这是 HR01 的模块入口。HR01 只做聚合、待办和风险展示，不成为人员、组织、合同、考勤等业务事实的最终权威。

## 小白先看这里

- `api/`：对外 API。
- `services/`：工作台业务编排，不直接改其他模块事实。
- `selectors/`：查询和聚合数据。
- `providers/`：从其他 HR 模块读取标准化数据。
- `models.py`：仅保存 HR01 自己的投影/配置数据。
- `permissions.py`：HR01 权限。
- `templates/` / `views/`：管理端页面。
- `tests/`：模块验收测试。

## 重构硬规则

1. 正式 API 使用 `/api/v1/hr/...`。
2. 跨模块数据只通过 Provider / Service / 事件读取或驱动，不直接写其他模块表。
3. 所有学校数据必须 tenant fail-closed。
4. Dashboard 展示结果可以重算，不能反向成为业务事实。
5. 旧入口保留兼容适配时必须明确标注 Legacy。
