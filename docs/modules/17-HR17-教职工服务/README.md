# HR17 教职工服务

- 实际代码：[`hr_self`](../../hr_self/)
- 页面入口：`/hr/self/`
- 现有前端：`hr_self/templates/hr_self/`、`static/hr/js/pages/hr17-self.js`
- 当前状态：本地主链可用（2026-08-31 76 项 MySQL 测试与本人浏览器入口已通过；未达生产上线）
- 当前任务：补齐 HR04/05/06/08/11 等缺失 Provider，以及待办、进度、文件、工资条聚合。
- 完成标准：本人身份唯一解析，HR03～HR16 数据只读聚合，IDOR 全拒绝。
