"""
accessibility/signals.py
"""

from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

from accessibility.middlewares import ACCESSIBILITY_CACHE_USER_KEYS
from accessibility.models import DefaultAccessibility
from employee.models import EmployeeWorkInformation
from horilla.signals import post_bulk_update


def _clear_accessibility_cache():
    keys = {
        key
        for cache_keys in ACCESSIBILITY_CACHE_USER_KEYS.copy().values()
        for key in cache_keys
    }
    if keys:
        cache.delete_many(keys)


def _clear_bulk_employees_cache(queryset):
    keys = set()
    for instance in queryset:
        if instance.employee_id and instance.employee_id.employee_user_id:
            keys.update(
                ACCESSIBILITY_CACHE_USER_KEYS.get(
                    instance.employee_id.employee_user_id.id, []
                )
            )
    if keys:
        cache.delete_many(keys)


@receiver(post_save, sender=EmployeeWorkInformation)
def monitor_employee_update(sender, instance, created, **kwargs):
    """
    This method tracks updates to an employee's work information instance.
    """

    _sender = sender
    _created = created

    if instance.employee_id and instance.employee_id.employee_user_id:
        user_id = instance.employee_id.employee_user_id.id
        cache_keys = ACCESSIBILITY_CACHE_USER_KEYS.get(user_id, [])

        for key in cache_keys:
            cache.delete(key)


@receiver(post_save, sender=DefaultAccessibility)
def monitor_accessibility_update(sender, instance, created, **kwargs):
    """
    This method is used to track accessibility updates
    """
    _sender = sender
    _created = created
    _instance = instance
    _clear_accessibility_cache()


@receiver(post_bulk_update, sender=EmployeeWorkInformation)
def monitor_employee_bulk_update(sender, queryset, *args, **kwargs):
    """
    This method is used to track accessibility updates
    """
    _sender = sender
    _clear_bulk_employees_cache(queryset)
