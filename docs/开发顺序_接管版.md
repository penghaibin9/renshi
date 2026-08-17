# 开发顺序（接管版）

> 本文件是 `agent/renshi-takeover-cleanup-20260810` 起的推荐施工顺序。  
> 目标：先把 HR01~HR12 收敛成统一、可运行、可验收的系统，再继续 HR13~HR18。

## 总原则

```text
先底座
→ 再 Authority
→ 再主链
→ 再跨域
→ 再体验
→ 最后全系统生产验收
```

任何阶段出现红灯，就留在当前阶段修，不跳关。

---

# C0｜仓库新手化 + 真相清洗

## 目标

让任何新手打开仓库都知道：

- 这是跃科高校人事系统，不是原版 Horilla；
- 当前真实开发分支与 main 关系；
- HR01~HR12 代码目录；
- 哪些报告已过时；
- 当前生产目标是 MySQL-only；
- 不允许继续无序扩张 HR13+。

## 必做

- [x] 替换根 README 为本项目中文入口
- [x] 新增新手入口
- [x] 新增本开发顺序
- [ ] 更新 docs 总索引，把“代码 HEAD 优先于历史 READY 报告”写成最高执行原则
- [ ] 建立 `CURRENT_STATE` 自动/半自动真实状态清单
- [ ] 将明显过时的 `FINAL_REPORT` / READY 声明标成历史记录，不再当 Gate

## Gate

```text
NEWCOMER ENTRY READY
REPOSITORY TRUTH BASELINE READY
```

---

# C1｜H0/A0 多学校租户底座收口

## 为什么第二个做

所有 HR 模块都依赖 tenant。底座没封板，后面任何“跨学校 403”都不可信。

## 必做

- 把 H0/A0 分支成果吸收到当前接管分支
- 统一 Tenant ↔ Company 映射
- request / job / event / provider 全部显式 tenant context
- 无 tenant 时 fail-closed
- 彻底禁止“默认第一所学校”“all 兜底”“前端过滤当隔离”
- 权限缓存切学校后立即失效
- 平台运营账号不得自动获得学校人事数据权限

## 必测

- A 校管理员不能读 B 校人员
- A 校管理员猜 B 校 ID = 403
- 后台 job 无 tenant = 拒绝执行
- provider 无 tenant = UNAVAILABLE/ERROR，不回退到全量
- 切换学校后旧权限缓存不生效

## Gate

```text
TENANT FOUNDATION GREEN
SECURITY NEGATIVE TESTS GREEN
```

---

# C2｜MySQL-only 基线统一

## 目标

把“文档说 MySQL，代码/CI 跑 PostgreSQL”彻底消掉。

## 必做

- `docker-compose.yml` 改为 MySQL 目标开发栈
- `horilla/settings/ci_test.py` 改为 MySQL
- GitHub Actions 提供 MySQL service
- 清理 PostgreSQL 专属 SQL / constraint / index / daterange / GIST 依赖
- fresh database migrate 全绿
- 回滚/重跑 migration 验证
- 大表索引和唯一约束按 MySQL 真实执行计划复核

## Gate

```text
MYSQL FRESH MIGRATE GREEN
MYSQL MODULE TEST GREEN
POSTGRESQL-SPECIFIC AUTHORITY DEPENDENCY = 0
```

---

# C3｜Django 接管与全局合同统一

## 目标

让 HR01~HR12 真正成为“一套 Django 系统”，而不是各 app 自己偷偷挂 URL。

## 必做

### App 注册

- 核对 HR01~HR12 `INSTALLED_APPS`
- HR09 / HR10 / HR12 正式注册前逐个通过 migration/check/test
- HR07 先恢复 GitHub 完整 app，再谈注册

### URL

逐步退出各 app 在 `AppConfig.ready()` 中直接改 `horilla.urls.urlpatterns` 的做法。

建立统一：

```text
horilla/urls.py
  └── /hr/... 页面入口
  └── /api/v1/hr/... API Root
```

### API

正式新 API：

```text
/api/v1/hr/...
```

旧：

```text
/api/hr/v1/...
```

只做 Legacy Adapter / redirect / deprecation metric，不再新增 handler。

### Permission

统一：

```text
hr.<domain>.<resource>.<action>
```

旧 permission 通过 alias mapping 迁移，不维持两套正式授权。

### Event

建立单一 Global Event Registry；同一业务事实禁止多个近义事件名。

## Gate

```text
ALL ACTIVE APPS REGISTERED
CANONICAL API GREEN
CANONICAL PERMISSION GREEN
GLOBAL EVENT CONTRACT GREEN
```

---

# C4｜HR02 → HR03 基础 Authority 封板

这两个是全系统地基。

## HR02 组织机构与编制岗位

重点验收：

- effective-dated 组织历史
- 部门/岗位启停
- 编制/岗位容量
- occupancy 并发防超卖
- as-of 历史查询
- tenant / scope
- Excel 导入：模板→校验→错误行→确认→审计

## HR03 教职工主档

重点验收：

```text
Person
≠ User
≠ Staff
≠ EmploymentRelationship
≠ Assignment
```

同时验：

- 多段聘用
- 主岗唯一
- 兼岗不覆盖主岗
- future-effective
- 历史 as-of
- correction/revision 而不是改旧事实
- HR02 position 引用正确

## Gate

```text
HR02 READY FOR ACCEPTANCE
HR03 READY FOR ACCEPTANCE
HR02↔HR03 E2E GREEN
```

---

# C5｜入人主链：HR04 → HR05 → HR07

## HR04 招聘

```text
用人计划
→ 招聘计划
→ 应聘
→ 筛选/面试/评议
→ 拟录用
→ Offer
```

不能直接创建正式 Staff。

## HR05 入职

```text
Offer/Handoff
→ 待报到
→ 材料核验
→ 报到
→ 账号/协同任务
→ HR03 Staff/Relationship/Assignment 激活
```

重复回调不能创建两个人。

## HR07 合同

这是当前优先修复模块：

1. 先找回/恢复完整 GitHub 代码
2. 核 models/migrations/tests/apps/urls
3. 再跑 MySQL fresh migrate
4. 再验 HR03 relationship → HR07 contract
5. 正式合同 FINAL/SIGNED/EFFECTIVE 后不可普通修改

## Gate

```text
HR04 READY
HR05 READY
HR07 READY
HR02→HR04→HR05→HR03 E2E GREEN
HR03→HR07 E2E GREEN
```

---

# C6｜HR06 → HR08 → HR09 → HR10 → HR11 → HR12

## HR06 人事异动

优先保留现有成熟结构，重点补：

- MySQL 并发
- Authority cutover
- Excel
- 浏览器 E2E
- HR02/03 双向一致性

## HR08 外聘

验：

- External Engagement 不冒充正式 EmploymentRelationship
- 外聘本人权限
- 到期/续聘/终止
- 教务/IAM Provider 不可用时明确 UNAVAILABLE

## HR09 教师资格与双师型

当前不是继续加 API，而是做运行接管：

- App 注册
- MySQL migration
- API/permission canonical
- rule version
- evidence verification
- revoke / renew / history

## HR10 培训进修与企业实践

当前代码面很宽，必须按纵向主链验，不按文件数量验：

```text
计划
→ 项目/活动
→ 报名/审批
→ 过程
→ 完成
→ 证据核验
→ Development Fact
→ HR09 / HR12 Provider 消费
```

## HR11 考勤与请假

重点补：

- Legacy cutover
- MySQL month close
- 重复打卡/重复月结幂等
- 调班/请假/加班冲突
- 时间事实冻结

## HR12 年度与聘期考核

先把代码纳入正式运行态，再验：

```text
PolicyVersion
→ Cycle
→ Population Snapshot
→ Evidence Snapshot
→ Review
→ Objection
→ Final Result
```

FINAL 后修订必须 Revision/Correction，不普通 UPDATE。

## Gate

```text
HR06 READY
HR08 READY
HR09 READY
HR10 READY
HR11 READY
HR12 READY
HR10→HR09→HR12 E2E GREEN
```

---

# C7｜HR01 聚合收口

HR01 最后收，而不是最先收。

原因：它不拥有下面模块的正式事实，只聚合。

## 必做

- Dashboard 只走 Provider/read model
- Provider UNAVAILABLE 不能显示成 0
- Metric Definition Authority 最终归 HR18
- 待办 drill-down 能回到真实 Authority
- 不允许工作台直接改下游正式事实
- 首页性能 / N+1 / 缓存 tenant key

## Gate

```text
HR01 READY FOR ACCEPTANCE
DASHBOARD NO-DIRECT-AUTHORITY-WRITE
```

---

# C8｜全系统生产闸门

只有这里全绿，才恢复 HR13 开发。

## 必测

### 全量回归

- MySQL 全测试
- migrations fresh + upgrade
- 关键浏览器 E2E
- 多角色正/负权限
- tenant 隔离

### Failure Injection

- Provider timeout / 500
- 重复 event
- worker down
- Outbox backlog
- MySQL deadlock
- 最后一个岗位并发抢占
- 请求超时但实际已成功
- object storage outage
- callback 丢失

### 运维

- 备份
- 恢复到新实例
- projection 重建
- 健康检查
- readiness
- production secret fail-closed
- DEBUG=True + production 必须拒绝启动

### Legacy

Authority cutover 后：

```text
LEGACY FORMAL WRITES = 0
```

旧书签/旧 API 被调用要有 deprecation metric，而不是静默继续写。

## 最终 Gate

```text
MYSQL FULL REGRESSION GREEN
CROSS-DOMAIN E2E GREEN
SECURITY / TENANT GREEN
FAILURE INJECTION GREEN
BACKUP / RESTORE GREEN
LEGACY FORMAL WRITES = 0
P0 = 0
P1 BLOCKING = 0
```

达到这里后：

```text
HR01~HR12 BASELINE SEALED
```

然后开发：

```text
HR13 职称评审
→ HR14 岗位聘任
→ HR15 薪酬福利
→ HR16 退休离校
→ HR17 教职工服务
→ HR18 人事数据中心
```

---

# 推荐提交粒度

不要一次提交几百个文件。

以后按这种粒度：

```text
fix(platform): align MySQL CI baseline
fix(platform): centralize HR URL registration
fix(hr07): restore contract app skeleton
fix(hr03): harden tenant negative tests
fix(hr04): normalize canonical API paths
```

一个 commit 只解决一个可说明、可回滚的问题。
