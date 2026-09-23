# 跃科高校人事 V14｜R11归档证据能力适配

基线V13，保留原完整HR01–HR18。本次选择移植非学历教育R11中通用的历史证据保护、版本回读和受控文件校验；不是整体合并两个业务系统。

入口：原HR12“结果归档”页。没有另建替代系统。

新增迁移：`hr_assessment.0028_archive_evidence_access`。需同步部署后端/前端并沿用原新数据库迁移程序；不能只替换CSS。原迁移无改写，工资目录、认证/权限后端、依赖、Docker配置及许可证保持。新增导出权限不自动授权。

先读：
- `docs/r11_fusion/PROVENANCE.md`：R11代码来源和取舍。
- `docs/r11_fusion/OPERATIONS.md`：操作、权限、接口和回退。
- `docs/r11_fusion/SCOPE_AND_VERIFICATION.md`：实际验证和阻断。

新功能61通过/2 MySQL跳过；浏览器25检查；原HR12/HR09继承失败有对照证据，不能说全系统全部通过。真实MySQL与生产登录未验收，release_approved=false。
