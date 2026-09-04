# docs 文档总索引

> 这是 `docs/` 的导航入口。  
> 从 2026-08-10 接管开始，统一执行：**当前代码/CI 事实 > 当前状态基线 > 设计总册 > 历史 READY/FINAL 报告。**  
> 历史报告可以帮助理解施工过程，但不能单独证明当前 HEAD 已验收。

---

# 0. 新手只先读 3 份

| 顺序 | 文件 | 作用 |
|---|---|---|
| 1 | `README_新手入口.md` | 10 分钟看懂仓库、目录、红线、状态词 |
| 2 | `CURRENT_STATE_2026-08-10.md` | 当前 GitHub 真相：谁成熟、谁阻塞、下一步是什么 |
| 3 | `开发顺序_接管版.md` | C0→C8 唯一推荐施工顺序和每阶段 Gate |

如果你只是跟着开发，不需要一上来读完几十份施工总册。

---

# 1. 全系统最高设计文件

当你需要修改架构、跨域合同、数据库、权限、事件、历史事实时，再读这些：

| 文件 | 用途 | 级别 |
|---|---|---|
| `00_高校人事系统全局架构与旧系统接管合同.md` | Authority、tenant、effective-dated、Provider/Event、MySQL、Legacy/Cutover、安全与最终 Gate | 最高设计合同 |
| `99_高校人事系统18模块施工总控与最终验收总册.md` | HR01~HR18 依赖、波次、全局验收 | 总控设计 |
| `HR01-HR18_总一致性与遗漏复审报告_终极版.md` | 历史一致性审计、P0/P1 合同冲突 | 参考审计 |
| `GlobalProductionGateChecklist.md` | 全系统 E2E / Failure Injection / 生产 Gate | 生产验收参考 |

**注意：**这些文件中的状态快照可能晚于/早于真实代码变化；业务规则仍有价值，但“完成/未完成”必须回到 `CURRENT_STATE_2026-08-10.md` 和当前 HEAD 复核。

---

# 2. HR01~HR18 业务施工总册

需要修某一个模块时，只读对应一册：

| 模块 | 文件 | Authority |
|---|---|---|
| HR01 | `01_HR01_人事工作台_施工总册_终极版.md` | 人事运营聚合，不拥有下游业务真值 |
| HR02 | `02_HR02_组织机构与编制岗位_施工总册_终极版.md` | 组织、部门、岗位、编制、结构历史 |
| HR03 | `03_HR03_教职工主档_施工总册_终极版.md` | Person / Staff / Employment / Assignment |
| HR04 | `04_HR04_招聘与人才引进_施工总册_终极版.md` | 招聘、应聘、选拔、Offer |
| HR05 | `05_HR05_入职管理_施工总册_终极版.md` | 报到、材料、激活、试用编排 |
| HR06 | `06_HR06_人事异动_施工总册_终极版.md` | 调动/转岗/身份变化 Case |
| HR07 | `07_HR07_合同与聘用_施工总册_终极版.md` | 合同/协议/聘期 |
| HR08 | `08_HR08_兼职外聘教师_施工总册_终极版.md` | External Engagement |
| HR09 | `09_HR09_教师资格与双师型_施工总册_终极版.md` | 资格/双师认定 |
| HR10 | `10_HR10_培训进修与企业实践_施工总册_终极版.md` | 教师发展 VERIFIED 事实 |
| HR11 | `11_HR11_考勤与请假_施工总册_终极版.md` | 时间/请假/月结事实 |
| HR12 | `12_HR12_年度与聘期考核_施工总册_终极版.md` | 年度/聘期考核正式结果 |
| HR13 | `13_HR13_职称评审_施工总册_终极版.md` | 职称结果 |
| HR14 | `14_HR14_岗位聘任_施工总册_终极版.md` | 聘任/聘期 |
| HR15 | `15_HR15_薪酬福利_施工总册_终极版.md` | 薪酬/福利/月结 |
| HR16 | `16_HR16_退休与离校_施工总册_终极版.md` | Exit / Retirement Fact |
| HR17 | `17_HR17_教职工服务_施工总册_终极版.md` | ESS 本人体验 |
| HR18 | `18_HR18_人事数据中心_施工总册_终极版.md` | 指标/报表/交换/报送 |

当前接管阶段：**暂停新增 HR13~HR18 功能，先封 HR01~HR12。**

---

# 3. `docs/hr/` 是施工过程资料

这里主要有四种文件：

```text
*_GAP_MATRIX       现状与目标差距
*_TASK_TREE        阶段任务树
*_RISK_REGISTER    风险登记册
*_Sxx_*            某次阶段验收/封板记录
```

使用方法：

```text
开发某模块
→ 先看当前状态基线
→ 看对应业务总册
→ 看 GAP/TASK/RISK
→ 回到真实代码
→ 按当前 Gate 验收
```

不要反过来因为某个 `*_S13_ProductionAcceptance.md` 写了 READY，就默认当前 HEAD 仍然 READY。

---

# 4. `docs/hr/legacy/` 是旧数据映射

Legacy 映射用于回答：

- 旧 Horilla 哪张表/哪个字段对应新 Authority？
- 如何迁移？
- 如何对账？
- 什么时候停止旧写？

它们不是新 Authority 模型定义。

所有旧写最终必须在 Cutover 后达到：

```text
LEGACY FORMAL WRITES = 0
```

---

# 5. `docs/hr/总控/` 是历史并行施工控制资料

当前保留用于追溯：

- `并行施工总控台账.md`
- `PATCH-02_API迁移矩阵.md`
- `PATCH-04_权限迁移矩阵.md`

从接管分支开始，新的开发顺序统一以：

`开发顺序_接管版.md`

为入口；遇到具体 API/权限迁移细节，再回看这些矩阵。

---

# 6. 文档优先级，必须记住

```text
1. 当前 Git HEAD + CI / 测试结果
2. CURRENT_STATE_2026-08-10.md
3. 开发顺序_接管版.md
4. 00 全局架构合同
5. 对应 HRxx 业务施工总册
6. GAP / TASK / RISK / Legacy Mapping
7. 历史 READY / FINAL / Acceptance 报告
```

其中第 7 类永远不能单独当合并依据。

---

# 7. 常用阅读路线

### 我只是新手，今天要知道做什么

```text
README_新手入口
→ CURRENT_STATE
→ 开发顺序_接管版
```

### 我要修 HR03

```text
CURRENT_STATE
→ 开发顺序 C4
→ 00 全局合同相关条款
→ 03_HR03 总册
→ docs/hr/HR03_GAP_MATRIX
→ hr_staff/ 真实代码
```

### 我要验收 HR07

```text
CURRENT_STATE（先确认 GitHub 交付断层）
→ 开发顺序 C5
→ 07_HR07 总册
→ HR07 Legacy/GAP/RISK
→ hr_contracts/ 真实目录
→ MySQL + test + E2E
```

### 我要判断能不能上线

```text
开发顺序 C8
→ GlobalProductionGateChecklist
→ 当前 GitHub Actions
→ MySQL full regression
→ Cross-domain E2E
→ Security / Tenant
→ Backup / Restore
```
