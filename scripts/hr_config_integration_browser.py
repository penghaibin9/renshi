#!/usr/bin/env python3
"""Real-browser acceptance for HR Configuration Center V1 + Integration Hub V1.

Runs against a real Django server and intentionally uses the production login
form and normal browser POSTs.  It never inserts configuration rows directly.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("HR_V1_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_V1_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_V1_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(os.getenv("HR_V1_BROWSER_ARTIFACT_DIR", "tests/artifacts/hr-config-integration-v1"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _open_details(page, summary_text: str):
    block = page.locator("details", has=page.locator("summary", has_text=summary_text)).first
    require(block.count() == 1, f"missing details block: {summary_text}")
    if not block.evaluate("el => el.open"):
        block.locator("summary").click()
    return block


def _submit_details(page, summary_text: str, fill) -> None:
    block = _open_details(page, summary_text)
    fill(block)
    with page.expect_navigation(wait_until="domcontentloaded"):
        block.locator('button[type="submit"]').click()
    page.wait_for_load_state("domcontentloaded")


def _select_first_real(select) -> None:
    options = select.locator("option")
    require(options.count() >= 2, "expected at least one real select option")
    select.select_option(index=1)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    evidence: list[dict[str, object]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        failure = None
        try:
            response = page.goto(BASE_URL + "/login/", wait_until="domcontentloaded")
            require(response is not None and response.status == 200, "login page unavailable")
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            with page.expect_navigation(wait_until="domcontentloaded"):
                page.locator('button[type="submit"]').click()
            require(urlsplit(page.url).path != "/login/", "production login failed")
            require(any(c["name"] == "sessionid" for c in context.cookies()), "sessionid missing")
            evidence.append({"step": "login", "status": "PASS", "finalUrl": page.url})

            response = page.goto(BASE_URL + "/settings/hr-configuration/", wait_until="domcontentloaded")
            require(response is not None and response.status == 200, "configuration center HTTP failure")
            require("高校人事配置中心 V1" in page.locator("body").inner_text(), "configuration center title missing")
            require(page.locator("tbody tr").count() >= 8, "bootstrap did not render eight workflows")
            onboarding_row = page.locator("tr", has_text="ONBOARDING").first
            require(onboarding_row.count() == 1, "HR05 ONBOARDING workflow missing")
            with page.expect_navigation(wait_until="domcontentloaded"):
                onboarding_row.locator("a", has_text="进入配置").click()
            workflow_match = re.search(r"/workflows/([0-9a-f-]+)/", urlsplit(page.url).path)
            require(workflow_match is not None, "cannot resolve workflow UUID from browser URL")
            workflow_id = workflow_match.group(1)
            evidence.append({"step": "bootstrap-eight-drafts", "status": "PASS", "workflowId": workflow_id})

            def add_field(block):
                _select_first_real(block.locator('select[name="field-form"]'))
                block.locator('input[name="field-key"]').fill("STAFF_NO")
                block.locator('input[name="field-label"]').fill("工号")
                block.locator('select[name="field-field_type"]').select_option("TEXT")
                block.locator('input[name="field-required"]').check()
                block.locator('input[name="field-sort_order"]').fill("10")
                block.locator('input[name="field-help_text"]').fill("学校正式工号")
            _submit_details(page, "添加字段", add_field)

            def add_approval(block):
                block.locator('input[name="approval-code"]').fill("HR_REVIEW")
                block.locator('input[name="approval-stage_code"]').fill("STAGE_02")
                block.locator('input[name="approval-role_code"]').fill("HR_STAFF")
                block.locator('input[name="approval-role_name"]').fill("人事管理员")
                block.locator('input[name="approval-data_scope"]').fill("SCHOOL")
                block.locator('input[name="approval-sort_order"]').fill("10")
                block.locator('select[name="approval-approval_mode"]').select_option("ANY")
            _submit_details(page, "添加审批角色", add_approval)

            def add_condition(block):
                block.locator('input[name="condition-code"]').fill("STAFF_NO_PRESENT")
                block.locator('input[name="condition-name"]').fill("已填写工号")
                block.locator('input[name="condition-source_stage_code"]').fill("STAGE_01")
                block.locator('input[name="condition-field_key"]').fill("STAFF_NO")
                block.locator('select[name="condition-operator"]').select_option("NOT_EMPTY")
                block.locator('input[name="condition-target_stage_code"]').fill("STAGE_02")
                block.locator('input[name="condition-priority"]').fill("10")
            _submit_details(page, "添加条件", add_condition)

            def add_notification(block):
                block.locator('input[name="notification-code"]').fill("ONBOARDING_CREATED")
                block.locator('input[name="notification-event_code"]').fill("CREATED")
                block.locator('select[name="notification-channel"]').select_option("IN_APP")
                block.locator('input[name="notification-recipient_role_code"]').fill("HR_STAFF")
                block.locator('input[name="notification-subject_template"]').fill("新入职待办")
                block.locator('textarea[name="notification-body_template"]').fill("请处理 {{ STAFF_NO }} 的入职事项")
                block.locator('input[name="notification-enabled"]').check()
            _submit_details(page, "添加通知", add_notification)

            def add_print(block):
                block.locator('input[name="print-code"]').fill("ONBOARDING_FORM")
                block.locator('input[name="print-name"]').fill("入职登记表")
                block.locator('select[name="print-output_format"]').select_option("HTML")
                block.locator('textarea[name="print-template_body"]').fill("<h1>入职登记</h1><p>工号：{{ STAFF_NO }}</p>")
                block.locator('input[name="print-enabled"]').check()
            _submit_details(page, "添加打印模板", add_print)

            def add_excel(block):
                block.locator('input[name="excel-code"]').fill("ONBOARDING_IMPORT")
                block.locator('input[name="excel-name"]').fill("入职导入模板")
                block.locator('select[name="excel-direction"]').select_option("IMPORT")
                block.locator('input[name="excel-sheet_name"]').fill("入职数据")
                block.locator('input[name="excel-enabled"]').check()
            _submit_details(page, "添加 Excel 模板", add_excel)

            def add_excel_column(block):
                _select_first_real(block.locator('select[name="excel_column-template"]'))
                block.locator('input[name="excel_column-field_key"]').fill("STAFF_NO")
                block.locator('input[name="excel_column-header"]').fill("工号")
                block.locator('input[name="excel_column-sort_order"]').fill("10")
                block.locator('input[name="excel_column-required"]').check()
                block.locator('input[name="excel_column-data_type"]').fill("TEXT")
                block.locator('input[name="excel_column-example_value"]').fill("T20260001")
            _submit_details(page, "添加 Excel 列", add_excel_column)

            body = page.locator("body").inner_text()
            require("可发布" in body, "configured workflow still fails publish validation")
            publish_button = page.locator('button:has-text("发布 v")').first
            require(publish_button.count() == 1 and publish_button.is_enabled(), "publish button unavailable")
            with page.expect_navigation(wait_until="domcontentloaded"):
                publish_button.click()
            require("已发布" in page.locator("body").inner_text(), "published state not visible")
            page.screenshot(path=str(ARTIFACT_DIR / "01-configuration-published.png"), full_page=True)

            api = context.request.get(BASE_URL + f"/api/v1/system/hr-configuration/workflows/{workflow_id}/published/")
            require(api.status == 200, f"published config API HTTP {api.status}")
            payload = api.json()["data"]
            require(len(payload.get("contentHash", "")) == 64, "published contentHash invalid")
            require(any(x["key"] == "STAFF_NO" for x in payload["fields"]), "published field missing")
            require(payload["approvalRoles"], "published approval role missing")
            require(payload["conditions"], "published condition missing")
            require(payload["notifications"], "published notification missing")
            require(payload["printTemplates"], "published print template missing")
            require(payload["excelTemplates"] and payload["excelTemplates"][0]["columns"], "published Excel template missing")
            evidence.append({"step": "publish-eight-layer-config", "status": "PASS", "contentHash": payload["contentHash"]})

            response = page.goto(BASE_URL + "/settings/integration-hub/new/?adapter=MASTERDATA_HTTP_JSON", wait_until="domcontentloaded")
            require(response is not None and response.status == 200, "Integration Hub create HTTP failure")
            form = page.locator('form[data-hrint-connection-form]').first
            form.locator('input[name="code"]').fill("MASTERDATA_CI")
            form.locator('input[name="name"]').fill("CI 主数据")
            form.locator('input[name="base_url"]').fill("http://127.0.0.1:9011")
            form.locator('input[name="enabled"]').check()
            form.locator('[data-hrint-config-fields] [data-hrint-key="health_path"]').fill("/health")
            form.locator('[data-hrint-secret-fields] [data-hrint-key="token"]').fill("CI-TOP-SECRET")
            with page.expect_navigation(wait_until="domcontentloaded"):
                form.locator('button[type="submit"]').click()
            connection_match = re.search(r"/connections/([0-9a-f-]+)/", urlsplit(page.url).path)
            require(connection_match is not None, "connection UUID not present after create")
            connection_id = connection_match.group(1)
            require("已加密保存" in page.locator("body").inner_text(), "credential encrypted indicator missing")
            require("CI-TOP-SECRET" not in page.content(), "credential leaked into browser HTML")

            profile_details = _open_details(page, "新增映射方案")
            profile_details.locator('input[name="profile-code"]').fill("STAFF_INBOUND")
            profile_details.locator('input[name="profile-name"]').fill("人员入站映射")
            profile_details.locator('select[name="profile-direction"]').select_option("INBOUND")
            profile_details.locator('input[name="profile-source_object"]').fill("staff")
            profile_details.locator('input[name="profile-target_domain"]').fill("HR03")
            profile_details.locator('input[name="profile-enabled"]').check()
            with page.expect_navigation(wait_until="domcontentloaded"):
                profile_details.locator('button[type="submit"]').click()
            mapping_card = page.locator("article", has_text="STAFF_INBOUND").first
            require(mapping_card.count() == 1, "mapping profile not rendered")
            with page.expect_navigation(wait_until="domcontentloaded"):
                mapping_card.locator("a", has_text="维护字段映射").click()

            mapping_details = _open_details(page, "添加字段映射")
            mapping_details.locator('input[name="source_field"]').fill("employeeNo")
            mapping_details.locator('input[name="target_field"]').fill("STAFF_NO")
            mapping_details.locator('input[name="transform_code"]').fill("IDENTITY")
            mapping_details.locator('input[name="required"]').check()
            mapping_details.locator('input[name="sort_order"]').fill("10")
            with page.expect_navigation(wait_until="domcontentloaded"):
                mapping_details.locator('button[type="submit"]').click()
            require("employeeNo" in page.locator("body").inner_text(), "field mapping not persisted")

            response = page.goto(BASE_URL + f"/settings/integration-hub/connections/{connection_id}/", wait_until="domcontentloaded")
            require(response is not None and response.status == 200, "connection detail unavailable")
            test_button = page.locator('button:has-text("测试连接")').first
            require(test_button.count() == 1, "test connection button missing")
            with page.expect_navigation(wait_until="domcontentloaded"):
                test_button.click()
            text = page.locator("body").inner_text()
            require("VERIFIED" in text or "已验证" in text or "连通性验证通过" in text, "real HTTP probe did not verify")
            require("CI-TOP-SECRET" not in page.content(), "credential leaked after probe")
            page.screenshot(path=str(ARTIFACT_DIR / "02-integration-verified.png"), full_page=True)

            contract = context.request.get(BASE_URL + f"/api/v1/system/integration-hub/connections/{connection_id}/contract/")
            require(contract.status == 200, f"integration contract API HTTP {contract.status}")
            contract_payload = contract.json()["data"]
            serialized = json.dumps(contract_payload, ensure_ascii=False)
            require("CI-TOP-SECRET" not in serialized, "credential leaked from integration contract")
            require(len(contract_payload.get("contractHash", "")) == 64, "integration contractHash invalid")
            require(contract_payload["mappings"] and contract_payload["mappings"][0]["fields"], "integration mapping contract missing")
            evidence.append({"step": "integration-real-http-probe", "status": "PASS", "contractHash": contract_payload["contractHash"]})

        except BaseException as exc:  # noqa: BLE001 - preserve browser evidence before re-raise
            failure = exc
        finally:
            try:
                context.tracing.stop(path=str(ARTIFACT_DIR / "trace.zip"))
            except PlaywrightTimeoutError:
                pass
            browser.close()

    result = {
        "status": "FAIL" if failure else "PASS",
        "baseUrl": BASE_URL,
        "evidence": evidence,
        "pageErrors": page_errors,
        "consoleErrors": console_errors,
    }
    (ARTIFACT_DIR / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    require(not page_errors, f"browser page errors: {page_errors}")
    require(not console_errors, f"browser console errors: {console_errors}")
    if failure:
        raise failure


if __name__ == "__main__":
    main()
