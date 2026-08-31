# HR16 退休与离校

> 设计事实源：`docs/16_HR16_退休与离校_施工总册_终极版.md`

## 这个模块负责什么

HR16 是辞职、调出、解除/终止、退休、离校交接、最终结算协同、关系/档案转移和退休事实的 Exit Authority。

## 接管策略

现有 Horilla `offboarding/` 不直接删除。先复用 Resignation、Notice Period、Exit Interview、Work Handover、FnF、任务/Pipeline/Dashboard 等技术能力，再把正式离退事实迁入 `hr_exit`。旧实现只有在无引用、完成数据映射且新链路验收后才删除。

## 固定技术合同

- API：`/api/v1/hr/exit`
- Permission：`hr.exit.*`
- Canonical events：`ExitEffective`、`RetirementEffective`
- 数据库：MySQL-only
- Tenant/Scope/Permission：fail-closed
- 辞职批准、合同结束、账号停用都不等于 Employment 已终止。
- employment end / contract end / appointment end / retirement date / access end 必须分开保存。

## 小白看代码顺序

1. `models/`：ExitCase、退休政策/预审、离校计划、Exit/Retirement Fact。
2. `services/`：审批、生效、交接 Gate、最终结算协同和更正。
3. `selectors/`：待办、进度、历史、退休预测与 as-of。
4. `integrations/`：IAM、资产、财务、ArchiveProvider 等。
5. `api/`：统一 `/api/v1/hr/exit`。
6. `tests/`：租户、权限、日期语义、重复生效、交接 Gate、MySQL 和跨域 E2E。
