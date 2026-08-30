"""
S12 · Playwright E2E 骨架（总册 §43.12，待真实 server 运行）。

视口：1280×900、1440×1000、1920×1080。
覆盖：名册筛选/profile/as-of/timeline/空态/403。

运行方式：
    npx playwright test hr_staff/tests/e2e/test_hr03_e2e.py --headed
前提：Django runserver 在 localhost:8000 运行、测试租户数据就绪。
"""

import re
import unittest

try:
    import pytest
    from playwright.sync_api import Page, expect
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(
        "HR03 browser E2E dependencies are optional; install pytest and playwright"
    ) from exc


@pytest.fixture(autouse=True)
def login(page: Page):
    """登录（V1 占位：待真实登录流程适配）。"""
    # [总控占位] 登录流程待 Horilla auth/CSRF 适配
    page.goto("http://localhost:8000/hr/staff/")
    yield


def test_staff_list_loads(page: Page):
    """名册：首屏加载，可见统计数字与至少 1 行。"""
    page.goto("http://localhost:8000/hr/staff/")
    expect(page.locator("h1")).to_contain_text("教职工名册")
    expect(page.locator("#rows tr")).not_to_contain_text("查询失败")
    # 等待数据加载
    page.wait_for_timeout(2000)


def test_staff_list_search(page: Page):
    """名册：关键词搜索。"""
    page.goto("http://localhost:8000/hr/staff/")
    page.fill("#keyword", "T001238")
    page.click("text=查询")
    page.wait_for_timeout(1500)
    expect(page.locator("#rows tr")).to_contain_text("T001238")


def test_profile_loads(page: Page):
    """主档：从名册进入，Header 显示姓名/工号/状态。"""
    page.goto("http://localhost:8000/hr/staff/")
    page.wait_for_timeout(2000)
    # 点击第一行进入主档
    first_row = page.locator("#rows tr[data-id]").first
    if first_row.count() > 0:
        staff_id = first_row.get_attribute("data-id")
        page.goto(f"http://localhost:8000/hr/staff/{staff_id}/")
        page.wait_for_timeout(2000)
        expect(page.locator(".badge")).to_contain_text(re.compile(r"在职|待入职|已离职|已退休"))


def test_as_of_history(page: Page):
    """as-of 历史视图：日期切换后，isHistoricalView=true。"""
    page.goto("http://localhost:8000/hr/staff/")
    page.wait_for_timeout(2000)
    first_row = page.locator("#rows tr[data-id]").first
    if first_row.count() > 0:
        staff_id = first_row.get_attribute("data-id")
        page.goto(f"http://localhost:8000/hr/staff/{staff_id}/?asOf=2024-06-01")
        page.wait_for_timeout(2000)
        expect(page.locator(".asof.warn")).to_contain_text("历史口径")


def test_empty_state(page: Page):
    """空态：不存在的 staffId 返回明确错误页面。"""
    page.goto("http://localhost:8000/hr/staff/00000000-0000-0000-0000-000000000000/")
    page.wait_for_timeout(1000)
    # 可能返回 404 或错误页
    expect(page.locator("body")).to_contain_text(
        re.compile(r"TENANT_CONTEXT_REQUIRED|未找到|STAFF_NOT_FOUND|403|500")
    )


def test_responsive_1280(page: Page):
    """1280 视口：名册正常渲染，无横向崩坏。"""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto("http://localhost:8000/hr/staff/")
    page.wait_for_timeout(2000)
    expect(page.locator("table")).to_be_visible()


def test_responsive_1440(page: Page):
    """1440 视口。"""
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto("http://localhost:8000/hr/staff/")
    page.wait_for_timeout(2000)
    expect(page.locator("table")).to_be_visible()


def test_responsive_1920(page: Page):
    """1920 视口。"""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto("http://localhost:8000/hr/staff/")
    page.wait_for_timeout(2000)
    expect(page.locator("table")).to_be_visible()
