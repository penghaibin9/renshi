from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatformTenantElevation(models.Model):
    """Audited, time-boxed platform access to one concrete school tenant."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="platform_tenant_elevations",
    )
    company = models.ForeignKey(
        "base.Company",
        on_delete=models.PROTECT,
        related_name="platform_access_elevations",
    )
    reason = models.TextField()
    reference = models.CharField(max_length=120, blank=True)
    granted_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revoked_platform_tenant_elevations",
    )
    revoked_reason = models.CharField(max_length=255, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("-granted_at", "-id")
        indexes = [
            models.Index(fields=("actor", "expires_at"), name="plat_el_actor_exp_idx"),
            models.Index(fields=("company", "expires_at"), name="plat_el_comp_exp_idx"),
        ]

    @property
    def is_active(self):
        now = timezone.now()
        return self.revoked_at is None and self.granted_at <= now < self.expires_at
