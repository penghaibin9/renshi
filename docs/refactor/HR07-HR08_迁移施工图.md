# HR07-HR08 迁移施工图

> 施工线 D：`agent/refactor-d-hr07-hr08`
> 接管目标：`agent/renshi-takeover-cleanup-20260810`
> 权威文档：`07_HR07_合同与聘用_施工总册_终极版.md`、`08_HR08_兼职外聘教师_施工总册_终极版.md`

## 1. 目录归属

| 模块 | 新 Authority 目录 | 旧能力来源 | 裁决 |
|---|---|---|---|
| HR07 合同与聘用 | `hr_contracts/` | `payroll.Contract` 及相关合同读取/页面 | **RECOVER + REWRITE/PROJECT**：先确认仓库真实代码与迁移状态，合同 Authority 归 HR07，旧 Contract 最终只做兼容投影 |
| HR08 兼职/外聘教师 | `hr_external/` | Horilla 当前人员/招聘/合同/文件/权限能力仅作基线与技术来源 | **NEW**：External Workforce 独立建模，不允许把普通 Employee 加一个“外聘”标签冒充 HR08 |

## 2. 小白目录规则

HR07、HR08 的模型、写服务、读取、跨域输出、接口和测试只放在各自模块目录。`payroll/`、`employee/`、`recruitment/` 等旧目录只作为迁移/兼容来源，不允许再新增 HR07/HR08 正式规则。

## 3. 搬迁顺序

1. HR07 先完成“实际代码恢复核验”：模型、迁移、服务、API、权限、测试、旧 Contract 投影逐项对齐，未确认前不删除任何 payroll contract 逻辑。
2. HR08 以 `HrPerson` 为身份根，建立 ExternalTeacherProfile / ExternalEngagement / ExternalAssignment 等独立事实，不创建重复自然人。
3. HR08 聘用审批完成后，由 HR07 管协议/合同；HR08 不直接拥有合同生命周期。
4. 外聘资格来自 HR09 provider；教学任务来自教务引用；访问权限必须有期限并在退出时回收。
5. 新旧对账、历史事实和租户/越权测试全部通过后，才冻结旧写入口并进入清理。

## 4. 当前已落地骨架

`hr_contracts/` 已有 README、恢复检查清单和 `module_contract.py`；`hr_external/` 已有 README、合同和测试。HR08 权威设计明确要求“外聘教师不是普通正式 Employee 的一个标签”。

## 5. 下一块代码

优先完成 **HR07 Recovery Checklist 中真实模型/迁移/API 的核验并补回归测试**；随后为 HR08 落第一条 **ExternalTeacherProfile + Engagement** 权威链路，不碰 HR07 的合同所有权。
