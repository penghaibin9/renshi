# 删除与归档规则

本轮只删除“运行时依赖已经被证明为 0”的东西；没有证据时一律不物理删除。

- **可直接删除**：生成缓存、临时截图、`__pycache__`、`.pyc`、测试临时目录。
- **先隔离再删**：重复静态资源、重复 shell、旧模板代际文件。必须先有模板解析/引用扫描和回归测试。
- **禁止按名称删除**：employee、attendance、leave、payroll、pms 等 app。即使页面不用，模型/服务/迁移/权限仍可能被 HR 业务调用。
- **禁止处理**：任何 migrations、正式业务模型、HR15 薪酬事实、权限/审计/幂等代码，除非另有业务缺陷证据。
- **发布门禁**：HR 模板不得继承 `index.html`；canonical shell 不得 include 旧 header/floating/language/profile 组件。
