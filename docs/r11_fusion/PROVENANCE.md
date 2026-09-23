# R11 → 人事 V13 代码适配来源

日期：2026-09-19。融合版本 V14。用户提供R11源码并明确授权借鉴有用代码。

主工程V13 SHA256：`7fa7536f13df4202eec14abcff754d16b9b4dc96f068ae28ea0e3f0a035bd478`。

来源R11 SHA256：`23e953e07a768b14488c5ca0e642baf53786f48d3f89d6c775dcc9d675de6d26`。

本轮按功能与算法适配，不把FastAPI、SQLAlchemy、Alembic、R11账号/权限、安装程序或合成学校直接复制到Django工程。人事V13并非R11的升级库；两个应用的版本号没有数据库兼容含义。

|编号|R11来源|人事落点|适配方式|
|---|---|---|---|
|R11-A|`backend/app/assessment_evidence.py` / verified_archive / assessment_projection|`backend/hr_assessment/services/archive_evidence.py`|适配到HR12指定结果版本、正式计算摘要与既有更正链；旧档案缺口不补写当前数据。|
|R11-B|`backend/app/assessment_evidence.py` / attachment_index / make_archive|`backend/hr_qualification/public.py + backend/hr_assessment/services/archive_evidence.py`|移植来源归属、附件版本索引和深复制思路；HR09只冻结元数据，未宣称原文件字节已核验。|
|R11-C|`backend/app/routes/files.py` / verify_file|`backend/hr_assessment/services/document_service.py`|适配原Django私有文件存储；同一打开流核对大小、摘要、普通文件类型及路径，返回已核验字节。|
|R11-D|`backend/app/services.py` / qualification_revision|`backend/hr_qualification/public.py`|借鉴当期资质及文件版本保留方式；不复制R11资格表、用户体系或工作流。|
|HR-NEW|`acceptance/R8_PDF_101_Clause_Tracker.json` / PDF条款8.5、10.5、10.7、12.1/12.5|`backend/hr_assessment/api/views_archive.py + frontend/static/hr/js/pages/hr12-archive-evidence.js`|在原HR12页面新增用途留痕、导出权限、五表XLSX、单份人工样本核对；不是复制积分算法。|

## 精确来源摘要

- `backend/app/assessment_evidence.py`：`1794fa96fa3ded722069cd4c8e07eed2136b0317168e9b2d476f288775dfe5ed`
- `backend/app/assessment_evidence.py`：`1794fa96fa3ded722069cd4c8e07eed2136b0317168e9b2d476f288775dfe5ed`
- `backend/app/routes/files.py`：`7730b69f16a1fe2fa9ea1350b5bd26d426c5d912aa3aa1584e688855d9094749`
- `backend/app/services.py`：`92d04d8ac71fbe41b2d65dd79bdc0b6cab0f229333d6a1adb6a5feb4f10a9f02`
- `acceptance/R8_PDF_101_Clause_Tracker.json`：`a7829c815505a95b3249241b174a0ab61c831769d7627094de8bac5f4f02a6e6`

## 许可记录

保留人事原LICENSE和版权。R11包内本轮未找到独立LICENSE文件，不能因此宣称所有来源均为无约束公共代码，也不替用户确认第三方授权链。本轮来源注明、改写适配和用户授权不等于完成逐组件商业许可审查。

## 不复制的业务

培训收入、课程人次、培训积分、湘培直通车接口/账号、R11首次安装迁移图、R11测试数据均未写入人事业务。新增单样本比对与导出API为人事适配代码，依据101条参考要求，不复制原积分计分公式。
