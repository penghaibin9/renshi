"""Base package.

Scheduled work is started only by ``run_legacy_scheduler``.  Importing a
Django app inside each Gunicorn worker must never create background threads.
"""
