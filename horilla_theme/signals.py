"""
Signals for the horilla_theme app
"""

# themes/signals.py
# Define your horilla_theme signals here
from django.db.models.signals import post_migrate
from django.db.utils import OperationalError, ProgrammingError
from django.dispatch import receiver

from .models import THEMES_DATA, HorillaColorTheme


@receiver(post_migrate)
def create_default_themes(sender, **kwargs):
    """
    Create default color horilla_theme after migration
    """
    # Only run for the horilla_theme app
    if sender.name != "horilla_theme":
        return

    # Check that the table exists. Do not return merely because one theme exists:
    # a previous interrupted post_migrate run may have created only part of the
    # default set, and get_or_create below is intentionally idempotent.
    try:
        HorillaColorTheme.objects.exists()
    except (OperationalError, ProgrammingError):
        # Table not created yet — skip silently
        return

    print("Creating default color themes...")
    created_count = 0

    for theme_data in THEMES_DATA:
        try:
            theme, created = HorillaColorTheme.objects.get_or_create(
                name=theme_data["name"], defaults=theme_data
            )
            if created:
                created_count += 1
                print(f"[OK] Created theme: {theme.name}")
            else:
                print(f"- Theme already exists: {theme.name}")
        except Exception as e:
            print(f"[ERROR] Error creating theme {theme_data['name']}: {str(e)}")

    print(f"\nSuccessfully created {created_count} themes.")
