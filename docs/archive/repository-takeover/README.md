# Repository takeover phase archive

2026-08-09 至 2026-08-17，仓库曾处于从上游 HRMS 底座向跃科高校人事产品收敛的集中接管阶段。

这一阶段产生过若干“当时有效、现在已经过期”的施工入口与状态快照，包括：

- `docs/README_新手入口.md`
- `docs/开发顺序_接管版.md`
- `docs/CURRENT_STATE_2026-08-10.md`
- `docs/FINAL_REPORT_2026-08-09.md`
- `docs/HorillaGlobalTakeoverMatrix.md`

这些材料包含旧分支名、阶段红灯、施工顺序、暂停策略、当时的模块完成判断和上游接管矩阵。随着 HR01–HR18 总集成生产基线于 2026-08-17 合入 `main`，它们已经不适合继续作为当前仓库导航或产品状态说明。

Repository Identity Cleanup 的处理原则：

- 不重写 Git 历史；
- 不修改 `LICENSE`；
- 不用历史 `READY` / `FINAL` 判断当前代码状态；
- 仍有长期迁移参考价值的接管矩阵保存在本目录；
- 纯阶段性状态快照从当前文档树移除，继续由 Git 历史承担审计追溯。

当前保存在本目录的材料：

- [`HorillaGlobalTakeoverMatrix.md`](HorillaGlobalTakeoverMatrix.md)：仅用于 Legacy/Cutover 与上游模块映射追溯，不作为当前产品身份或完成状态。

需要查看已退出文档树的旧状态报告时，可从 Git 历史中查看它们在 `61fc1d0ece15605a3d14fe72d490c3dd0c1fd2e0` 及更早提交中的原文。

当前导航请使用：

- 根目录 `README.md`
- `docs/00_文档总索引.md`
- 当前 `main` 的 CI / 测试 / migration 证据

本目录仅用于追溯，不作为当前产品完成状态依据。
