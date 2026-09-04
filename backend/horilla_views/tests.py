from types import SimpleNamespace

from django.test import SimpleTestCase

from horilla_views.cbv_methods import assign_related
from horilla_views.generic.cbv.views import HorillaFormView


class ImportRelationTests(SimpleTestCase):
    def test_assign_related_preserves_last_matching_import_value(self):
        first = SimpleNamespace(code="A")
        last = SimpleNamespace(code="A")

        result = assign_related(
            {"profile": {"owner": "A"}},
            "profile",
            {"profile__owner": [first, last]},
            {"profile__owner": "code"},
        )

        self.assertIs(result["owner"], last)


class HorillaResponseTests(SimpleTestCase):
    def test_reload_targets_are_deduplicated_without_losing_order(self):
        response = HorillaFormView.HttpResponse(
            targets_to_reload=["#first", "#first", "#second"]
        )
        content = response.content.decode()

        self.assertEqual(content.count("$(`#first`).click();"), 1)
        self.assertLess(content.index("#first"), content.index("#second"))

    def test_default_reload_targets_do_not_leak_between_responses(self):
        first = HorillaFormView.HttpResponse(targets_to_reload=["#custom"])
        second = HorillaFormView.HttpResponse()

        self.assertIn(b"#custom", first.content)
        self.assertNotIn(b"#custom", second.content)
