from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from notifications.templatetags.notifications_tags import register_notify_callbacks
from payroll.widgets.component_widgets import (
    AllowanceConditionalVisibility,
    DeductionConditionalVisibility,
    StyleWidget,
)
from recruitment.widgets import RecruitmentAjaxWidget

from base.widgets import CustomModelChoiceWidget, CustomTextInputWidget


@override_settings(STATIC_URL="/static/")
class WidgetRenderingSecurityTests(SimpleTestCase):
    def test_delete_widgets_escape_dynamic_attributes(self):
        attack = '" autofocus onfocus="alert(1)'
        for widget in (CustomModelChoiceWidget(), CustomTextInputWidget()):
            with self.subTest(widget=type(widget).__name__):
                rendered = str(
                    widget.render(
                        "field",
                        None,
                        attrs={"delete_url": f"/delete/?next={attack}"},
                    )
                )
                self.assertNotIn(' autofocus onfocus="alert(1)', rendered)
                self.assertIn("&quot;", rendered)

    def test_script_widgets_use_canonical_static_urls(self):
        widgets = (
            AllowanceConditionalVisibility(),
            DeductionConditionalVisibility(),
            StyleWidget(),
            RecruitmentAjaxWidget(),
        )
        for widget in widgets:
            with self.subTest(widget=type(widget).__name__):
                rendered = str(widget.render("field", None, attrs={}, renderer=None))
                self.assertIn('/static/', rendered)
                self.assertNotIn('//static/', rendered)

    @patch(
        "notifications.templatetags.notifications_tags.reverse",
        side_effect=lambda name: f"/{name}/",
    )
    def test_notification_callback_tag_rejects_script_injection(self, _reverse):
        rendered = str(
            register_notify_callbacks(
                badge_class='badge</script><img src=x onerror=alert(1)>',
                callbacks="refreshBadge,alert(1)//",
            )
        )

        self.assertIn("register_notifier(refreshBadge);", rendered)
        self.assertNotIn("alert(1)", rendered)
        self.assertNotIn("</script><img", rendered)
        self.assertIn('notify_badge_class = "live_notify_badge"', rendered)


class DatabaseTemplatePreviewSecurityTests(SimpleTestCase):
    def test_preview_is_rendered_in_a_sandboxed_iframe(self):
        root = Path(__file__).resolve().parents[2]
        source = (
            root
            / "backend/horilla_dbtemplate/templates/admin/horilla_dbtemplate/template/preview.html"
        ).read_text(encoding="utf-8")

        self.assertIn("<iframe", source)
        self.assertIn("sandbox", source)
        self.assertIn('srcdoc="{{ rendered_srcdoc }}"', source)
        self.assertNotIn("{{ rendered }}", source)
