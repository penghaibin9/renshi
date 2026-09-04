from django.conf import settings
from django.urls import path

from .views import *

legacy_gdrive_patterns = [
    # path("local/", local_setup, name="local"),
    # path("start-stop/", local_Backup_stop_or_start, name="start_stop"),
    # path("delete/", local_Backup_delete, name="backup_delete"),
    path("gdrive/", gdrive_setup, name="gdrive"),
    path("gdrive-start-stop/", gdrive_Backup_stop_or_start, name="gdrive_start_stop"),
    path("gdrive-delete/", gdrive_Backup_delete, name="gdrive_delete"),
]

# Production backups are exclusively handled by the encrypted
# create_production_backup/run_production_backup_scheduler pipeline. The
# historical Google Drive UI creates plaintext staging files and must never be
# reachable in production, even by an administrator.
urlpatterns = [] if getattr(settings, "IS_PRODUCTION", False) else legacy_gdrive_patterns
