from django.contrib.auth.models import Permission
from django.test import TestCase


class FormalTitleResultPermissionTests(TestCase):
    def test_result_permission_exists_after_migrate(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="hr_title",
                content_type__model="titleapplicationcase",
                codename="hr.title.result",
            ).exists()
        )
