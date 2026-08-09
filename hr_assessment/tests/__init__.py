"""
HR12 Assessment — 测试文件索引（生产级）。

生产级覆盖：
- test_imports.py       — 全量 import 验证（10 断言）
- test_providers.py     — Provider 契约 + 真实 ORM（14 断言）
- test_security.py      — 18 安全场景
- test_concurrency.py   — 10 并发场景
- test_e2e_annual.py    — 年度主链 15 步
- test_e2e_term.py      — 聘期链 6 步
- test_e2e_objection.py — 异议链 11 步 + Provider 失败
- test_data_quality.py  — 15 数据质量
- test_ai_boundary.py   — 11 断言（AI + A11y + Perf）
- test_accessibility.py — 12 A11y
- test_performance.py   — 14 断言（Perf + Cutover）
- test_cutover.py       — 6 Cutover 冒烟
- factories.py          — 11 个工厂函数
"""

from hr_assessment.tests.test_imports import TestAllImports  # noqa: F401
