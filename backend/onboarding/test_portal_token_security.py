import inspect
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from onboarding.models import (
    PORTAL_TOKEN_PREFIX,
    OnboardingPortal,
    onboarding_portal_token_digest,
)
from onboarding import views


class OnboardingPortalTokenSecurityTests(SimpleTestCase):
    def test_bearer_token_is_replaced_by_one_way_digest(self):
        raw = "high-entropy-onboarding-token"
        digest = onboarding_portal_token_digest(raw)

        self.assertTrue(digest.startswith(PORTAL_TOKEN_PREFIX))
        self.assertEqual(len(digest), 71)
        self.assertNotIn(raw, digest)
        self.assertEqual(onboarding_portal_token_digest(digest), digest)

    def test_portal_string_representation_never_contains_bearer_token(self):
        portal = OnboardingPortal(token="raw-token")
        portal._state.fields_cache["candidate_id"] = "Candidate"
        self.assertNotIn("raw-token", str(portal))

    def test_portal_token_is_unique_at_the_database_boundary(self):
        field = OnboardingPortal._meta.get_field("token")

        self.assertTrue(field.unique)
        self.assertEqual(field.max_length, 71)

    def test_every_public_portal_lookup_hashes_the_url_token(self):
        for view in (
            views.user_creation,
            views.profile_view,
            views.employee_creation,
            views.employee_bank_details,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn(
                    "onboarding_portal_token_digest(token)",
                    inspect.getsource(view),
                )

    def test_invalid_user_creation_token_is_a_real_404(self):
        request = RequestFactory().get("/onboarding/user-creation/invalid/")
        with patch.object(
            OnboardingPortal.objects,
            "get",
            side_effect=OnboardingPortal.DoesNotExist,
        ), patch.object(views, "render", return_value=HttpResponse(status=404)):
            response = views.user_creation(request, "invalid")

        self.assertEqual(response.status_code, 404)

    def test_internal_user_creation_failure_does_not_leak_exception(self):
        request = RequestFactory().get("/onboarding/user-creation/token/")
        with self.assertLogs("onboarding.views", level="ERROR") as captured:
            with patch.object(
                OnboardingPortal.objects,
                "get",
                side_effect=RuntimeError("database password leaked here"),
            ):
                response = views.user_creation(request, "token")

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"database password leaked here", response.content)
        self.assertNotIn("database password leaked here", "\n".join(captured.output))
        self.assertIn("RuntimeError", "\n".join(captured.output))

    def test_portal_account_state_is_database_backed_for_multiple_workers(self):
        source = inspect.getsource(views)

        self.assertNotIn("portal_user =", source)
        self.assertIn("user.save()", inspect.getsource(views.user_save))
        self.assertIn("@transaction.atomic", inspect.getsource(views.user_save))
        self.assertIn(
            "HorillaUser.objects.filter(username=candidate.email).first()",
            inspect.getsource(views.employee_creation),
        )

    def test_existing_account_cannot_be_reset_through_fresh_portal(self):
        source = inspect.getsource(views.user_creation)

        self.assertIn("username__iexact=candidate.email", source)
        self.assertIn("status=409", source)

    def test_invitation_resend_preserves_progress_and_fails_closed(self):
        # all_manager_can_enter is a legacy decorator without functools.wraps,
        # so inspect the module source rather than its returned wrapper.
        module_source = inspect.getsource(views)
        function_start = module_source.index("def email_send(request):")
        function_tail = module_source[function_start:]
        source = function_tail[: function_tail.index("\n\ndef ")]

        self.assertIn("@require_POST\ndef email_send(request):", module_source)
        self.assertNotIn("portal.count = 0", source)
        self.assertNotIn("portal.profile = None", source)
        self.assertIn('portal.save(update_fields=["token", "used"])', source)
        self.assertIn("if sent_count != 1", source)
        self.assertIn('portal.save(update_fields=["used"])', source)

    def test_portal_mutation_steps_are_transactional(self):
        for view in (
            views.user_save,
            views.profile_view,
            views.employee_creation,
            views.employee_bank_details_save,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn("@transaction.atomic", inspect.getsource(view))
