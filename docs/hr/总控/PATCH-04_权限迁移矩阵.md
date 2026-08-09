# PATCH-04 迁移矩阵：Permission namespace（总控裁决：不迁移）

> 依据：《99_高校人事系统18模块施工总控与最终验收总册》PATCH-04 + 《HR01-HR18_总一致性与遗漏复审报告》P0-06。
> ⚠️ **总控最终裁决（2026-08-09 08:20）：保持 `hrNN.*` 命名全系统统一，不迁移到 canonical `hr.<domain>.*`。**

---

## 1. 为什么裁决不迁移

- 已交付代码 **统一使用 `hr04.* / hr08.* / hr03.* / hr05.*`**（HR04 permissions 18 处 + api 大量、HR08 constants 20 处 + api 大量、HR05 16 处、HR03/HR01 少量）。
- 权限码是系统内部配置，前端/客户不可见；命名风格一致即可，不构成"三套 namespace 分裂"（分裂指同一模块两种命名，现无此情况）。
- 强行改名 = 权限常量 + 装饰器 + `has_perm()` 调用 + 测试断言 + admin 注册全部改，风险高收益低。

**结论：与 API 前缀同理，保持现状统一，不做形式迁移。**

## 2. 现状盘点（供参考，不执行迁移）

| 模块 | 当前 namespace | 涉及面 |
|---|---|---|
| HR01 | `hr.dashboard.*`（部分 `hr01.*`） | `hr_control_center` |
| HR02 | `hr.organization.*`（部分 `hr02.*`） | `hr_structure` |
| HR03 | `hr.staff.*`（部分 `hr03.*`） | `hr_staff` |
| HR04 | `hr04.*` | `hr_recruitment`（permissions 18 处 + api 大量 + tests） |
| HR05 | `hr05.*` | `hr_onboarding`（permissions 16 处 + api/services 大量） |
| HR08 | `hr08.*` | `hr_external`（constants 20 处 + api 大量 + tests） |
| HR11 | `hr.time.*` | `hr_time`（已用 canonical 风格） |

> 说明：已存在少量 mixed（如 HR01/02/03 有 `hr.dashboard.*/hr.organization.*/hr.staff.*` 也有 `hrNN.*`）。这不影响运行，只是命名风格不完全统一。总控建议后续新权限码统一跟本模块主导风格，不强制批量改名。

## 3. 未来约束（防新分裂）

- 新窗口（HR06/07/09/10/12-18）权限码命名跟随本模块总册既有风格，或明确声明一种，禁止同一模块混用两套。
- 若未来做权限审计/角色矩阵导出时发现歧义，再单独清理（低优先）。

## 4. 迁移预案（如未来需要）

1. `PermissionAliasMapping` 迁移先行（旧码→新码自动继承授权，不重复授权）。
2. 代码替换：`permissions.py` 常量 + 装饰器参数 + `has_perm()` 调用 + 测试断言。
3. 一个 app 一提交，每步测试绿。

## 5. Gate（仅未来迁移时适用）

```text
全 app canonical 权限码 + PermissionAliasMapping 迁移 + 测试全绿 + alias 不重复授权
```
