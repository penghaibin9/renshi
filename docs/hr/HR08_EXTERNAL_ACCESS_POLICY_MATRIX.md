# HR08_EXTERNAL_ACCESS_POLICY_MATRIX（初版 · HR08-S0 输出）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md` §66-68/§94-99/§104/§105/§138.12-14/§138.18
> 状态：`DRAFT_V1`

## 1. 原则（硬门）

1. **一个 IAM 身份 + 多 scoped grants**（§98）：一个 Person 多 Engagement 不重复建账号；账号有效性由所有 active grants 聚合。
2. **expires_at 不得超过 Engagement**（§67/§95）：`expires_at <= engagement.end_at + allowed_grace`，grace 由 policy 配置（默认 7 天归档，不能无限延长）。
3. **退出权限回收闭环**（§138.12）：`ExternalEngagementEnding` → 撤销全部 grants；一个 Engagement 退出不能误杀另一个（§138.14）。
4. **回收失败不反转 Engagement**（§105）：`Engagement=ENDED` + `Access Revocation=FAILED_RETRYABLE` + `Risk=CRITICAL`。
5. **外聘最小权限**（§94）：默认不授予 `HR_EMPLOYEE/FULL_OA/ADMIN`。

## 2. 目标系统 × 角色 × 默认策略

| target_system | role_code | 默认授予类别 | scope_json 示例 | 默认过期规则 | 说明 |
|---|---|---|---|---|---|
| EXTERNAL_PORTAL | `EXTERNAL_TEACHER_PORTAL` | 全部已激活 Engagement | `{engagements:[id...]}` | = engagement.end_at | 外聘本人工作台（任务/证据/协议/意愿） |
| ACADEMIC | `ACADEMIC_TEACHER` | 教学类类别 | `{terms:[学期], courses:[...]}` | = engagement.end_at + 0 | 教务教师身份（S6 `HrExternalAcademicIdentity`） |
| LMS | `LMS_TEACHER` | 教学类类别 | `{courses:[...]}` | = engagement.end_at | 仅在承担课程任务时 |
| LIBRARY | `LIBRARY_EXTERNAL` | 按校规 | `{validity:[...]}` | = engagement.end_at | |
| CAMPUS_CARD | `CAMPUS_ACCESS_LIMITED` | 有入校需求类别 | `{zones:[...]}` | = engagement.end_at + grace | |
| DOOR_ACCESS | `DOOR_LIMITED` | 有入校需求类别 | `{buildings:[...]}` | = engagement.end_at | |
| VPN | `VPN_EXTERNAL` | 需要远程访问 | `{}` | = engagement.end_at | |
| OA | `OA_EXTERNAL_LIMITED` | 按校规 | `{modules:[...]}` | = engagement.end_at | 非默认 |
| RESEARCH | `RESEARCH_EXTERNAL` | 科研合作类别 | `{projects:[...]}` | = engagement.end_at | 非默认 |

## 3. 类别 × 权限裁剪（示例）

| 类别 | EXTERNAL_PORTAL | ACADEMIC_TEACHER | LMS | CAMPUS_CARD | RESEARCH | HR_EMPLOYEE/FULL_OA/ADMIN |
|---|---|---|---|---|---|---|
| INDUSTRY_PROFESSOR | Y | 按任务 | 按任务 | Y | 按任务 | N |
| PART_TIME_TEACHER | Y | Y（授课任务） | Y | Y | N | N |
| SKILL_MASTER | Y | N | 按任务 | Y | N | N |
| HONORARY_TITLE | 称号视图 | **N** | N | 可配(不默认) | N | N |
| PROJECT_EXPERT | Y | N | N | 按校规 | Y | N |

> 规则：**Category 裁剪 → Engagement 期限 → Assignment scope → 任务 scope** 逐层收窄；不能因类别可教学就全校教务权限（§138.8）。

## 4. 账号生命周期（§95/§138.18）

```
Engagement ACTIVE → AccessGrant 按 engagement 创建（expires_at ≤ end_at）
Scheduler：
  T-30 提醒续聘/到期
  T-7 确认续聘或退出
  end_at → 撤销 grants
  grace 到期 → 硬回收
Engagement 结束 → 不能存在无理由长期 Active access
```

## 5. 回收闭环（§66/§105）

- `ExternalEngagementEnding` → 对每个 grant 发起 `HrExternalProvisioningRequest`（operation=REVOKE）；
- 目标系统（IAM/教务/图书馆/门禁/VPN/OA/科研）逐个回收；
- 失败语义：`FAILED_RETRYABLE`（重试）→ 重试仍失败 `FAILED` + `Risk=ACCESS_REVOCATION_FAILED (CRITICAL)`；
- 全部回收成功才 `HrExternalAccessGrant.status=REVOKED`；`HrExternalExitCase` 记录回收结果。

## 6. 安全矩阵（§122 相关项）
- 外聘教师只能读本人/本任务（`ASSIGNED_TASKS`/`SELF`）；
- 外聘不能读正式员工主档；
- IAM grant scope 校验；access expiration 强一致；
- 后台 job/event 显式 tenant（§59）；禁止跨 tenant 回收；
- Excel 禁止直接建账号/开放权限（§110）。

## 7. 现状缺口（S0 清点）
- 现状：`Employee.save()` 自动建 HorillaUser（username=email、password=phone、默认 ownprofile 权限）+ 自动 EmployeeWorkInformation —— 这是 HR08 严禁复用的入口；
- 现状：无任何 access grant / expires_at / scoped role 概念；HorillaUser 与 Employee 一一绑定；
- HR08 目标：`HrExternalAccessGrant`（S2）+ provisioning/reconciliation（S6）+ 调度回收（S8），**不建第二套账号引擎**，复用 HR05 provisioning 基础若已交付（未交付则 Provider 占位）。
