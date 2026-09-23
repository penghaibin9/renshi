# 跃科高校人事｜本批代码收尾 V13

日期：2026-09-19。唯一连续基线：V12。原包 SHA256：`5a455889d2f863808adacc1fee7eeeff8dc217ee3995e12929b1be7e966a1c57`。

## 交付判断

原工程内完成本批收尾修复、回归、差异核对和交付整理；没有重建系统或展开新的横向模块。此处“收尾”指本轮修改有可复核证据，**不是 P0–P7 所有生产、客户或复杂薪酬验收完成**。`release_approved=false`。

产品和测试代码 23 项差异，说明 4 份，共 27 项：17 修改、10 新增、0 删除。完整工程 10827 个文件。原 519 份迁移文件、104 份薪酬目录文件、依赖与发布配置、许可证逐文件保持原字节。未重算历史工资，没有新增数据库迁移。

## 已实际修复的六组事项

|编号|收尾内容|实际结果和边界|
|---|---|---|
|C01|结果页与迁入台账统一|共用同一行来源检查；主任职、同校引用、唯一来源、逐行审计、行数与终态/检查点一致才确认。未知旧回执、坏状态、重复关系、缺审计不报成功；有效的结束历史仍可核对。超过范围明确未知，不当零。|
|C02|名册快速查询与失败|请求序号隔离加超时；旧响应不盖新结果。查询开始停用旧导出；失败清旧名单，未知人数不展示为正常零值，手动查询可恢复。原条件、路由、授权和页面布局不改变。|
|C03|两种备份恢复共用检查|原加密灾备入口接入交接包的安全解压；固定加密文件清单、大小/摘要/认证、资源限额、重复路径、链接、文件目录冲突检查。兼容原加密备份中的一个 `.` 根目录；不接受重复根。|
|C04|独立恢复目标|两个入口拒绝生产空媒体、源码、静态、备份/交接/回执目录及其祖先/后代、符号路径；数据库名大小写别名也拒绝。恢复中途出现已有文件时不删除它，不宣称跨资源原子恢复。|
|C05|内容指纹与证据文件|v2 纳入更多模型字段定义并严格核对学校/范围/时间/哈希格式/23 模型。缺 MySQL 证据或不是独立库时总体 BLOCKED；私有密钥、全新 JSON、完整写成后独占发布，不覆盖旧证据或配置。仅验证所提供证据，不能认证收集人或真实恢复。|
|C06|代码和测试整理|修正两个旧文案/岗位夹具问题，补齐旧完整应用测试中的必填数据；保留依赖阻断、不改产品规则换通过。兼容原 readbackScope，新增明确 verificationScope；老 v1 指纹需重新采集，不能改头伪升级。|

## 实际回归结果

|检查|实际结果|说明|
|---|---|---|
|HR03 可在既有隔离应用集中执行的集合|270/270 通过|包含新增 16 个回读回归；SQLite ORM/单元/契约，不是生产全量。|
|HR03 完整集合尝试|仍 3 个环境错误入口|对应 22 个依赖完整学校应用/真实 MySQL 的方法未在所需环境通过；原 MySQL assert 保留。不能写“HR03 全集通过”。|
|HR05 集合|355 执行：346 通过、9 跳过|MySQL 专用项未执行。|
|HR04 集合|239 执行：220 通过、19 跳过|原 MySQL/并发专用项未执行。|
|HR15 原薪酬集合|215/215 通过|工资代码未改；不代表银行、税务、学校实账。|
|新增文件/密码学/恢复目标/证据 I/O 检查|64/64 通过|实际文件、TAR、AES 与进程内并发输出；MySQL 查询与恢复明确模拟，不是真实恢复。|
|原 V12 恢复保护|24/24 通过|原证据夹具补充真实采集器已有的范围、时间元数据，断言未放松。|
|原交接包合同|11/11 通过|含静态门；静态门项不另累计成恢复案例。|
|原 P0–P2 工具安全与更早门禁|31/31、6/6 通过|单元/文件，不是 Docker 执行。|
|原名册页面实际浏览器|25/25 通过，页面脚本异常 0|原 Django 模板/JS/CSS，明确隔离网络响应；没有借此宣称真实上传/登录。|
|模型漂移检查|原 mini_settings：无模型变化遗漏|不是 MySQL 迁移或完整部署检查。|
|补丁/源码 ZIP|封包后实际应用、逐文件比对及 CRC 检查|详见 package-verification.json；不以只生成补丁代替应用。|

不同集合重叠或证据层次不同，不相加成完整业务流程数。实际命令/退出码、首次失败、修正、最终日志均随 Evidence 交付。

## 反例与旧测试问题

原 V12 上新增回读首轮 11 方法中 7 个失败，证据格式首轮 11 方法中 9 失败、1 错误；原名册 UI 7 检查中 6 项未通过。V13 对应最终回归已通过。

原 V12 HR03 全量隔离收集本就有 1 个失败、4 个错误。两处旧测试问题已修：岗位占用正例不能使用 DRAFT 岗位，独立资格入口不能绑定已废弃 UI 文案。正式任职仍拒绝未启用岗位。两个完整学校 applier 夹具补齐原来就要求的人员类别/关系类型，但仍待完整环境执行。其余 3 个环境入口未隐藏，22 方法清单独立保留。

原静态检查只匹配大小写敏感的库名比较，强化为 casefold 后按新实现更新精确断言；两个恢复入口的真实调用拒绝测试另有证据。误填测试标签和第一次使用禁用迁移的设置所产生失败日志均保留，没有当成生产通过。

## 明确没有完成的事项

- P2：没有 Docker/MySQL；原 horilla.settings 仍缺 environ。实际只读入口返回 BLOCKED/exit2，直接安装源下载也失败。未删依赖、改设置或解除 MySQL 门禁。
- 真实学校/院系/本人权限、原生 Cookie/MFA、私有文件、全历史迁移/锁并发和独立库恢复尚未验收。
- 本轮浏览器是 Linux Chromium、1440/1093/768/390 四组视口。未使用真实 Windows 显示缩放、文件选择器、打印或规模性能证据；全局壳层与网络响应是明确夹具。
- 复杂薪酬**代码能力**仍按原 V8–V12 限制：校院两级预算、年度预发清算、负向追扣、复杂缴费反算、专项税务及跨期更正等，不能全部写成“只差学校配置”。
- 学校真实制度、数据/工资样本、外部提供方联调、培训签认、许可审查、商业试点与第二校部署仍需独立完成。没有新增客户、签约、发薪或外部开通事实。

细目见 `REMAINING.json` 和状态工作簿。源码收尾不会自动关闭这些事项。

## 发布与回退

前后端、模板与恢复工具必须同步更新；本轮没有新迁移，但旧版升级仍须执行所有历史迁移。只在独立预发布合并；不得清库、覆盖并行工作或将整个共享数据库外发给单校。

新证据 schema 为 `yueke.delivery-content-proof.2`，不与 v1 混比；从同一维护/备份点用相同私有随机密钥重新采集源库和独立恢复库。23 模型和模型字段定义不是全物理数据库、媒体、外部系统或客户验收的证明，摘要也不是收集者数字签名。

恢复 SQL 与媒体切换不是一个事务：中途失败要检查独立目标库和媒体，不能盲目重复导入非空库；目标账号只能操作独立恢复库。细节见 OPERATIONS.md。工具回退不等于业务回退，优先前向修复，不删除事实配合旧代码。

## 本轮文件差异

- `V13_START_HERE.md`（新增）
- `backend/horilla_backup/handover.py`（修改）
- `backend/horilla_backup/management/commands/restore_production_backup.py`（修改）
- `backend/horilla_backup/management/commands/restore_school_handover_package.py`（修改）
- `backend/horilla_backup/management/commands/verify_production_backup.py`（修改）
- `backend/horilla_backup/production.py`（修改）
- `backend/hr_onboarding/management/commands/hr_delivery_snapshot.py`（修改）
- `backend/hr_onboarding/services/delivery_evidence_io.py`（新增）
- `backend/hr_onboarding/services/delivery_snapshot.py`（修改）
- `backend/hr_staff/api/imports.py`（修改）
- `backend/hr_staff/services/import_receipt_service.py`（修改）
- `backend/hr_staff/services/import_service.py`（修改）
- `backend/hr_staff/templates/hr_staff/staff_list.html`（修改）
- `backend/hr_staff/tests/test_closeout_receipts_v13.py`（新增）
- `backend/hr_staff/tests/test_round4.py`（修改）
- `backend/hr_staff/tests/test_round4_export_import.py`（修改）
- `backend/hr_staff/tests/test_v2_roster_contract.py`（修改）
- `docs/closeout_v13/CLOSEOUT.md`（新增）
- `docs/closeout_v13/OPERATIONS.md`（新增）
- `docs/closeout_v13/REMAINING.json`（新增）
- `scripts/check_school_handover_contract.py`（修改）
- `scripts/compare_hr_delivery_snapshots.py`（修改）
- `tests/closeout_v13/__init__.py`（新增）
- `tests/closeout_v13/test_backup_safety.py`（新增）
- `tests/closeout_v13/test_evidence.py`（新增）
- `tests/closeout_v13/test_private_evidence_io.py`（新增）
- `tests/delivery_v12/test_restore_guards.py`（修改）
