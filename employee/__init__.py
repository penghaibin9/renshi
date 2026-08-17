# Import lightweight accessibility hooks only.
#
# IMPORTANT: scheduler is intentionally NOT imported here. Starting APScheduler
# inside a Django/Gunicorn import creates one scheduler per web worker and can
# execute cross-tenant jobs without an explicit school context. Use:
#   python manage.py run_employee_scheduler
from employee import accessibility  # noqa: F401
