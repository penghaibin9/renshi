# Repository takeover phase archive

2026-08-10 至 2026-08-17，仓库曾处于从上游 HRMS 底座向跃科高校人事产品收敛的集中接管阶段。

当时的两份顶层施工入口：

- `docs/README_新手入口.md`
- `docs/开发顺序_接管版.md`

包含了旧分支名、阶段红灯、C0–C8 施工顺序以及“暂停某些模块”的临时控制信息。随着 HR01–HR18 总集成生产基线于 2026-08-17 合入 `main`，这些内容已经不适合继续作为当前仓库导航和产品状态说明。

Repository Identity Cleanup 将上述文件从当前文档树移除，但**不重写 Git 历史**。需要审计接管过程时，可从 Git 历史中查看它们在 `61fc1d0ece15605a3d14fe72d490c3dd0c1fd2e0` 及更早提交中的原文。

当前导航请使用：

- 根目录 `README.md`
- `docs/00_文档总索引.md`
- 当前 `main` 的 CI / 测试 / migration 证据

本目录仅用于追溯，不作为当前产品完成状态依据。
