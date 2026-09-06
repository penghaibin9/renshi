"""The shared account menu must render before an optional Employee exists."""

from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class AccountProfileHeaderTests(SimpleTestCase):
    def render(self, user):
        request = SimpleNamespace(user=user, session={"selected_company": "1"})
        return render_to_string("base/navbar_components/profile_section.html", {"request": request, "user": user})

    def test_school_account_uses_escaped_identity_and_no_empty_employee_image(self):
        html = self.render(SimpleNamespace(username="<school-admin>"))
        self.assertIn("data-account-menu-toggle", html)
        self.assertIn("data-account-avatar", html)
        self.assertIn("&lt;school-admin&gt;", html)
        self.assertNotIn("<school-admin>", html)
        self.assertNotIn('src=""', html)
        self.assertNotIn("ui-avatars.com", html)
        self.assertIn("账号已登录", html)
        self.assertNotIn("离线", html)
        self.assertNotIn("我的资料", html)
        self.assertIn("退出登录", html)

    def test_empty_username_has_a_visible_non_personnel_fallback(self):
        html = self.render(SimpleNamespace(username="", employee_get=None))
        self.assertIn("data-account-avatar", html)
        self.assertIn("账", html)
        self.assertNotIn('src=""', html)

    def test_existing_employee_keeps_avatar_presence_and_profile_links(self):
        employee = SimpleNamespace(
            get_avatar="/static/images/ui/default_avatar.jpg", get_full_name="Teacher Example",
            check_online=True, employee_work_info=SimpleNamespace(company_id=SimpleNamespace(id=1)),
        )
        html = self.render(SimpleNamespace(username="employee-account", employee_get=employee))
        self.assertNotIn("data-account-avatar", html)
        self.assertIn('/static/images/ui/default_avatar.jpg', html)
        self.assertIn("Teacher Example", html)
        self.assertIn("在线", html)
        self.assertIn("我的资料", html)
        self.assertIn("修改密码", html)
