# HR08_EXTERNAL_CATEGORY_MATRIX（初版 · HR08-S0 输出）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §5/§18/§28/§93/§136
> 状态：`DRAFT_V1` —— 默认值只是建议，学校可配置（`HrExternalCategory` tenant 化），**不可配置掉**：tenant 隔离、Person 去重人工控制、Engagement effective dates、Agreement gate、audit、access expiry、version、exit/revoke、历史不可变。

## 1. 类别模型

`HrExternalCategory`（tenant_id, code, name）+ 策略字段：

| 字段 | 说明 |
|---|---|
| code / name | 类别标识与显示名（tenant 内唯一） |
| requires_open_selection | 是否要求公开遴选 |
| requires_ethics_review | 是否要求师德/伦理审查 |
| requires_teacher_qualification | 是否要求教师资格 |
| requires_industry_experience | 是否要求行业经历 |
| agreement_type_code | HR07 协议类型引用（Provider 占位，HR07 交付后映射） |
| default_engagement_months | 默认聘期月数（可空） |
| allow_multiple_assignments | 是否允许同 Engagement 多 Assignment |
| allow_teaching / allow_research | 是否允许教学/科研任务 |
| access_policy_code | 访问策略引用（见 EXTERNAL_ACCESS_POLICY_MATRIX） |
| settlement_policy_code | 结算策略引用（HR15 边界） |
| is_active / version | 启用状态与乐观锁 |

## 2. 内置类别默认矩阵

| code | name | 公开遴选 | 伦理审查 | 教师资格 | 行业经历 | 默认聘期(月) | 多Assignment | 教学 | 科研 | 说明 |
|---|---|---|---|---|---|---|---|---|---|---|
| PART_TIME_TEACHER | 兼职教师 | 可配 | Y | Y* | 可配 | 12 | Y | Y | N | *按校规；承担教学任务需教师资格 |
| EXTERNAL_TEACHER | 外聘教师 | 可配 | Y | Y* | 可配 | 12 | Y | Y | 可配 | |
| INDUSTRY_ADJUNCT | 产业兼职教师 | Y | Y | N | Y | 12 | Y | Y | Y | 八部门《产业兼职教师管理办法》主线 |
| INDUSTRY_PROFESSOR | 产业教授 | Y | Y | N | Y | 24 | Y | Y | Y | 高价值专项管理（HR08-02） |
| SKILL_MASTER | 技能大师 | 可配 | Y | N | Y | 24 | Y | 可配 | N | 技能大师工作室（HR08-02） |
| INDUSTRY_MENTOR | 产业导师 | 可配 | Y | N | Y | 12 | Y | N | Y | |
| VISITING_PROFESSOR | 客座教授 | 可配 | Y | N | 可配 | 12 | Y | 可配 | Y | |
| GUEST_PROFESSOR | 讲座教授 | 可配 | Y | N | 可配 | 12 | Y | N | Y | |
| HONORARY_TITLE | 荣誉/名誉称号 | N | Y | N | N | 可配(可为空) | N | N | N | **Title ≠ Engagement**：不默认开放教学/门禁/OA/教务权限 |
| EXTERNAL_EXPERT | 外聘专家 | 可配 | Y | N | Y | 12 | Y | N | Y | |
| PRACTICE_INSTRUCTOR | 实践教学指导教师 | 可配 | Y | N | Y | 12 | Y | Y | N | |
| RETIRED_REHIRE_EXTERNAL | 退休返聘（外聘） | 可配 | Y | 按校规 | 可配 | 12 | Y | 可配 | 可配 | 复用原 HrPerson；不得恢复旧正式关系 |
| PROJECT_EXPERT | 项目专家 | 可配 | Y | N | Y | 按项目 | Y | N | Y | |
| OTHER | 其他 | 可配 | Y | 按校规 | 可配 | 可配 | Y | 可配 | 可配 | |

> `*`：`requires_teacher_qualification` 由学校配置；如候选人无 HR09 事实，HR08 只采集 staging evidence 提交 HR09 核验（§10），不复制第二套教师资格台账。

## 3. 荣誉性身份必须区分（§5.2）

`HONORARY_TITLE` 等仅表示称号，**不自动意味着**：有课、有工资、有门禁、有 OA、有教务权限。
```
Title Appointment ≠ Engagement ≠ Assignment
```
- `HrExternalTitleAppointment`（称号任命，如客座/荣誉/产业教授称号）独立于 `HrExternalEngagement`；
- 荣誉称号到账期自动生成"称号到期提醒"，但不自动续、不自动开放权限。

## 4. 关键策略不可配置项（§136）
- tenant 隔离（类别必须 tenant 化，禁止跨校共享配置）
- Person 去重人工控制
- Engagement effective dates（start<end；状态机）
- Agreement gate（默认 `REQUIRED_BEFORE_ACTIVATION`，§93）
- audit、access expiry、version、exit/revoke、历史不可变

## 5. 类别 → 审批流默认映射（§28 政策模板）
产业兼职教师/产业教授默认工作流：
```
按需设岗 → 公开遴选(可配置适用情形) → 择优聘请 → 资格/师德/冲突审查 → 协议管理 → 入校授权
```
学校可调整工作流，但不可关闭：审批、身份验证、agreement、task definition、effective dates、audit。
