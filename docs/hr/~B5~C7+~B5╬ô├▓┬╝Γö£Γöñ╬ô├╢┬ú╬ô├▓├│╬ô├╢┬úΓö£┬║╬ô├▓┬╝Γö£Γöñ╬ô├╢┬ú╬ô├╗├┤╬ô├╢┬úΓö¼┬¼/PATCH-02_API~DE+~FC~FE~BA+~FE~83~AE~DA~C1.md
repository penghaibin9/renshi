# PATCH-02 迁移矩阵：API Root（总控裁决：不迁移）

> 依据：《99_高校人事系统18模块施工总控与最终验收总册》PATCH-02 + 《HR01-HR18_总一致性与遗漏复审报告》P0-02。
> ⚠️ **总控最终裁决（2026-08-09 08:20）：保持 `/api/hr/v1` 全系统统一，不迁移到 `/api/v1/hr`。**

---

## 1. 为什么裁决不迁移

99 总册要求 canonical `/api/v1/hr` 的**真实目的**是防止"系统内两套 API 根分裂"。核查发现：

- **已交付代码 100% 统一使用 `/api/hr/v1`**：7 个 app 的 `urls.py`（HR04 61 处 / HR08 52 处 / HR05 34 处 / HR02 27 处 / HR03 27 处 / HR01 13 处）+ 几十处 API views 硬编码 + 20+ 个前端 JS + 14 个模板。
- 系统内完全自洽，**不存在两套根分裂**，99 总册要防的问题本就不存在。
- 强行迁移 ≈ 几百处修改 + 高概率破坏施工中窗口；收益仅为满足文档字面写法。

**结论：文档适配代码，代码不返工适配文档。**

## 2. 现状盘点（供参考，不执行迁移）

| app | 模块 | API 前缀（统一） |
|---|---|---|
| `hr_control_center` | HR01 | `/api/hr/v1/home/` |
| `hr_structure` | HR02 | `/api/hr/v1/structure/` |
| `hr_staff` | HR03 | `/api/hr/v1/staff/` + `/api/hr/v1/corrections/` |
| `hr_recruitment` | HR04 | `/api/hr/v1/recruitment/` |
| `hr_onboarding` | HR05 | `/api/hr/v1/onboarding/` + `/api/hr/v1/prehire/` |
| `hr_external` | HR08 | `/api/hr/v1/external-teachers/` |
| `hr_time` | HR11 | `/api/hr/v1/time/` |

## 3. 未来约束（防新分裂）

- **新开窗口（HR06/07/09/10/12-18）必须用 `/api/hr/v1`** 与现有代码一致，禁止混用 `/api/v1/hr`。
- 若未来客户有明确的 API 网关/开放平台规范要求再评估整体迁移，作为独立专项一次做完（一个 app 一提交）。

## 4. 迁移预案（如未来需要，按此执行）

1. 保留旧路径为 Legacy Adapter（同一 view 函数 + deprecation metric）。
2. 新增 canonical 路径，view 逻辑复用同一函数（不复制 handler）。
3. 前端 `api-client.js` base URL + HR17 Gateway + HR18 Drilldown 同步。
4. 全部 contract test 以新路径为 Authority，旧路径命中计数后下线。

## 5. Gate（仅未来迁移时适用）

```text
全 app 迁移完成 + contract test 以新路径为 Authority 全绿 + 旧路径仅 adapter
```
