# 新手入口：10 分钟看懂 renshi 仓库

> 产品：跃科高校人事管理与教师发展系统  
> 仓库：`penghaibin9/renshi`  
> 适用对象：第一次接手仓库、对 Django/Git/高校人事业务不熟悉的人。

## 1. 先认清这是什么

本仓库不是原版 Horilla，也不是 18 个互不相干的页面包。

```text
Horilla 历史兼容底座
        ↓ 按 Authority 接管、迁移、投影和退出旧写
跃科 HR01～HR18 高校人事系统
        ↓
同一岗位、同一候选人、同一教职工的完整生命周期
```

旧代码可以继续承担兼容读取和迁移，但不能永久与新 Authority 双主、双写。

---

## 2. 第一次只读这 4 份

1. [`CURRENT_STATE_2026-09-04.md`](CURRENT_STATE_2026-09-04.md)：现在真实做到哪里、红灯在哪里。
2. [`开发顺序_接管版.md`](开发顺序_接管版.md)：当前唯一施工顺序。
3. [`CORE_BUSINESS_FLOW_ACCEPTANCE.md`](CORE_BUSINESS_FLOW_ACCEPTANCE.md)：怎样才算核心业务 100% 通。
4. [`00_文档总索引.md`](00_文档总索引.md)：需要查某个模块或跨域合同再进入。

准备上线、备份或故障处理时读 [`PRODUCTION_RUNBOOK.md`](PRODUCTION_RUNBOOK.md)。

不要先翻历史 `FINAL/READY` 报告，也不要根据某张截图判断完成度。

---

## 3. 先记住 6 个词

### Authority

某类正式业务事实的唯一所有者。例如 HR03 拥有 Person / Staff / Employment / Assignment；其他模块只能通过正式合同消费或请求变更，不能另建一套长期双写。

### Tenant / Scope

学校与数据范围。任何请求、后台任务、事件、导出和外部调用都必须带明确 tenant 与 scope；不明确时必须拒绝，不能默认第一所学校或全量。

### Effective-dated / as-of

组织、岗位、任职、合同、职称、聘任、薪酬和离校等事实必须能解释“某一天是什么状态”。新状态生效不能删除旧历史。

### Final / Effective / Closed

正式结果状态。进入这些状态后，普通编辑不能原地覆盖；更正必须产生 Revision / Correction / 新版本和审计记录。

### Provider / Command / Event

跨模块写入合同。禁止从一个业务域直接 import 另一个域的正式模型后 `.save()`；要通过明确的 Provider、Command API 或可持久化事件协作。

### Gate

验收闸门。代码很多、页面漂亮、测试部分通过都不等于可上线；必须通过当前 exact HEAD 的 MySQL、权限、业务、浏览器、Docker、安全与恢复门。

---

## 4. 真实目录怎么认

```text
backend/                  Django 配置、公共底座与 HR01～HR18 后端
frontend/                 页面模板、样式、JavaScript 与静态资源
scripts/                  数据准备、检查、真实浏览器验收脚本
tests/                    视觉基线及跨层测试资源
.github/workflows/        GitHub Actions 生产门禁
deploy/                   Gunicorn、Nginx、启动与部署脚本
docs/                     当前规则、业务总册、验收与运维文档
.runtime/                 本机运行数据，不提交 Git
```

HR01～HR18 代码目录：

```text
HR01 backend/hr_control_center/    HR10 backend/hr10_development/
HR02 backend/hr_structure/         HR11 backend/hr_time/
HR03 backend/hr_staff/             HR12 backend/hr_assessment/
HR04 backend/hr_recruitment/       HR13 backend/hr_title/
HR05 backend/hr_onboarding/        HR14 backend/hr_appointment/
HR06 backend/hr_changes/           HR15 backend/hr_payroll/
HR07 backend/hr_contracts/         HR16 backend/hr_exit/
HR08 backend/hr_external/          HR17 backend/hr_self/
HR09 backend/hr_qualification/     HR18 backend/hr_data/
```

日常 Django 命令从仓库根目录执行；根目录 `manage.py` 会装载 `backend/`。

---

## 5. 核心业务到底是什么

核心流程不是把 HR01～HR18 菜单逐个点开，而是用同一套真实数据、多个真实角色连续完成：

```text
工作台
→ 组织/岗位/编制
→ 招聘/候选人/拟录用/Offer
→ 入职报到/材料/激活
→ 教职工主档与正式占编
→ 合同签署/生效
→ 人事异动并保留旧岗位历史
→ 外聘/资格/培训发展
→ 考勤请假
→ 年度/聘期考核
→ 职称评审
→ 岗位聘任
→ 薪酬核算/发放
→ 退休/离校/释放岗位
→ 本人查看正式结果
→ 数据中心快照/报表/归档
```

每一步都必须检查：入口、动作、刷新后的结果、下一角色回读、旧历史。完整 Case 见 [`CORE_BUSINESS_FLOW_ACCEPTANCE.md`](CORE_BUSINESS_FLOW_ACCEPTANCE.md)。

---

## 6. 什么不能冒充完成

下面任何一种都不能写“核心流程已通”：

- 只验证菜单和页面不报错；
- 点击后出现 toast，但刷新状态没变化；
- 使用 mock、固定统计数字或手工改数据库跳过前置状态；
- 只跑 SQLite/PostgreSQL，未在 MySQL 签字；
- 只有模块单测，没有上下游、角色和浏览器证据；
- 正例通过，但跨租户、越权、幂等、并发、历史不可变未测；
- 外部 Provider 没有真实回执，却把“已入队”显示成最终成功；
- 文档写 READY，但当前 PR 的必需检查仍红。

---

## 7. 每天只按这条线施工

```text
查看 CURRENT_STATE
→ 选择唯一红灯/唯一业务阶段
→ 找对应 Authority 和验收 Case
→ 阅读对应 HRxx 总册
→ 只改最小闭环
→ 跑精准测试
→ 跑受影响上下游回归
→ 提交到当前施工分支
→ 让 PR 的全局门禁验证
→ 全绿后才进入下一阶段
```

不并行铺多个模块，不因为页面多就按菜单数量推进。

---

## 8. Git 最少安全命令

```bash
# 当前分支
git branch --show-current

# 当前改动
git status

# 只检查明确文件
git diff -- path/to/file.py

# 只添加本次明确文件，禁止 git add -A
git add path/to/file.py path/to/test_file.py

git commit -m "fix(hrxx): close ... workflow"
```

禁止：

```bash
git add -A
git push --force
git reset --hard
直接在 main 上施工
为了测试绿而关闭 tenant / permission / audit / production gate
```

是否推送、合并，以当前 PR 和负责人授权为准。

---

## 9. 改业务前必答 10 问

1. 这个正式事实归哪个 HRxx Authority？
2. 是否会形成第二套长期事实或双写？
3. tenant / scope 不明确时是否 fail-closed？
4. 是否存在跨域直接模型写入？
5. 新状态会不会删除或篡改历史？
6. FINAL / EFFECTIVE / CLOSED 后是否仍可普通更新？
7. 重复请求、重复事件、重复回调是否幂等？
8. 最后一个岗位/编制并发争抢是否会超占？
9. 导入、导出、附件、审计和错误行是否完整？
10. 当前证据是否来自 MySQL + exact SHA，而不是旧报告？

任何一项答不清楚，留在当前阶段补齐，不继续向后铺功能。

---

## 10. 统一状态词

```text
CODE COMPLETE            代码主体存在
MODULE TEST GREEN        单模块测试通过
MYSQL GREEN              MySQL 迁移与相关测试通过
INTEGRATION GREEN        上下游状态链通过
BROWSER GOLDEN GREEN     真实角色在浏览器完成状态变化与回读
READY FOR ACCEPTANCE     可以进入正式验收
PRODUCTION READY         全系统所有必需 Gate、负例和恢复签字通过
```

`CODE COMPLETE`、`MODULE TEST GREEN`、`READY FOR ACCEPTANCE` 都不等于 `PRODUCTION READY`。

当前真实状态只认 [`CURRENT_STATE_2026-09-04.md`](CURRENT_STATE_2026-09-04.md) 和当前 PR exact HEAD。
