# V12｜开发与复验入口

## 连续边界

基线 V11：SHA256 `35a8dfcd768f26677cd0515a2d2bea716048cce204f8f0512aad84d4d0489a16`。原目录和模块保留。本轮修改HR03导入核对、原交付包安全解压，新增内容比对命令与受控同人链测试；没有新迁移，没有重算原工资，没有重建系统。

## 新接口

`GET /api/hr/v1/staff/import/{jobId}/receipt` 返回历史迁入核对JSON；`?format=xlsx`返回3工作表。沿用 `hr.staff.import`、真实学校上下文和SCHOOL范围。响应no-store/nosniff；下载产生IMPORT_RECEIPT_DOWNLOAD审计。读取锁住原任务以与逐行提交观察一致，不修改原业务数据。

`verificationStatus=VERIFIED` 不等于整张源表全成功；请同时检查 failed、pending。该字段只核对同校历史Person/Staff/来源用工/来源PRIMARY任职及逐行审计。旧无规范UUID回执、缺四层或缺审计均返回NOT_VERIFIED，不伪造历史事实。

## 新命令

`hr_delivery_snapshot` 仅MySQL8.4、确认同一备份点后读取23个模型的计数/结构/HMAC。`scripts/compare_hr_delivery_snapshots.py`只比较私有证据；始终不批准上线。完整含义见P5手册。

## 可重复执行的受控测试（只在隔离测试环境）

从 backend 目录执行：

```bash
python -m django test hr_staff.tests.test_delivery_receipts_v12 hr_staff.tests.test_imports --settings=hr_staff.tests.sqlite_settings --noinput
python -m django test hr_recruitment.tests.test_delivery_chain_v12 --settings=hr_recruitment.tests.sqlite_settings --noinput
python -m django test hr_onboarding.tests --settings=hr_onboarding.tests.sqlite_settings --noinput
python -m django test hr_recruitment.tests --settings=hr_recruitment.tests.sqlite_settings --noinput
python -m django test hr_payroll.tests --settings=hr_payroll.tests.sqlite_settings --noinput
```

从项目根目录执行：

```bash
python -m unittest discover -s tests/delivery_v12 -v
python -m unittest discover -s tests/round11 -v
python scripts/check_school_handover_contract.py
python scripts/run_hr_p012_gate.py --report /private/new-p012-report.json
```

上述SQLite settings是既有受控测试配置，不得部署到学校。测试任务从既有录用接受边界起步，使用真实服务/ORM/权限记录，但学校成员来源为夹具，并明确关闭测试文件扫描；不证明生产登录/MFA/CSRF全旅程或MySQL锁。测试只用虚构数据，不写入客户资料。

## 失败历史

P3首轮测试将AssignmentService第二个位置参数误当audit_actor（实际为policy），更正测试为显式audit_actor_user_id后重跑通过，没有放宽产品校验。P4首次测试使用激活前的旧对象读取结案条件，重新从库回读后通过；测试导入的旧TestCase别名也改为模块引用，避免重复计算旧测试。

旧交付静态门禁按被移除的extractall/错误文本匹配而失败；改为检查新的允许成员类型、重复/碰撞/资源限制和同一safe_extract_archive调用，并用实际恶意tar测试保护行为。原失败日志保留，不把字符串门禁通过当成真实恢复验收。

## 新增界面检查

原HR03模板及脚本的10项Playwright检查通过，包括真实Blob下载、503保留所选文件、原任务重试、新文件重置旧回执、1093宽度边界和零页面脚本异常。网络回应使用明确的UI夹具，实际新接口与四层核对另由ORM测试覆盖，不拼成一次全链。

首次截图中名册根元素依赖外部盒模型重置，1093视口的padding把页面撑宽；本轮给原hr03-staff.css的根页面增加局部border-box并复验，未更换整体样式。编译的全局Tailwind样式仍需原构建过程，不以隔离截图替代P2完整静态资源验收。
