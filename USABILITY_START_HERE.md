# 高校人事系统易用性候选 R5 — START HERE

日期：2026-09-17

## 当前唯一基线

本目录是 R4 基线上继续完成的 R5 易用性收口。

R5 不新增业务菜单，重点是降低学习成本和重复填写：

1. HR01～HR18 每模块至少 23 个上下文问法；
2. 14 段真人式办理路线继续保持；
3. 表单“已有值”与“已带入”分开标识；
4. 空选填项才会在简洁模式隐藏；已有值绝不隐藏；
5. 选填项统一显示“可选”；
6. 新增“提交前核对”，只显示缺项/改动字段名称和计数，不显示敏感值；
7. 脱敏 AI Prompt 可以带必填完成度与缺失字段名称，但不携带任何字段值。

## 先跑的门禁

```bash
python scripts/check_hr_usability_contract.py
python scripts/hr_usability_static_browser.py
python scripts/hr_lifecycle_real_chromium.py
```

## 真实 QA 仍必须执行

R5 的 Chromium 测试验证的是交付 CSS/JS 和 14 段点击行为。真实业务事务仍需 Django + MySQL QA 环境执行 `scripts/hr_real_browser_click.py` 以及各模块业务写入/审批/回读测试。

不要把 `SOURCE_USABILITY_R5_CLOSURE_COMPLETE` 解读为生产环境已经验收通过。
