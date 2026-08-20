"""Tenant-aware model manager used by legacy Horilla models."""

import logging

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Q
from django.db.models.query import QuerySet

from horilla.horilla_middlewares import _thread_locals, get_selected_company
from horilla.signals import (
    post_bulk_update,
    post_model_clean,
    pre_bulk_update,
    pre_model_clean,
)

logger = logging.getLogger(__name__)
django_filter_update = QuerySet.update


def update(self, *args, **kwargs):
    request = getattr(_thread_locals, "request", None)
    self.request = request
    pre_bulk_update.send(sender=self.model, queryset=self, args=args, kwargs=kwargs)
    result = django_filter_update(self, *args, **kwargs)
    post_bulk_update.send(sender=self.model, queryset=self, args=args, kwargs=kwargs)
    return result


django_model_clean = models.Model.clean


def clean(self, *args, **kwargs):
    pre_model_clean.send(sender=self._meta.model, instance=self, **kwargs)
    result = django_model_clean(self)
    post_model_clean.send(sender=self._meta.model, instance=self, **kwargs)
    return result


models.Model.clean = clean
setattr(QuerySet, "update", update)


class HorillaCompanyManager(models.Manager):
    """
    Company/tenant scoped manager.

    In takeover mode ``TENANT_FAIL_CLOSED=True`` means a tenant-aware model
    queried without an explicit tenant context returns an empty queryset.
    Background code must use ``tenant_context(company_id)`` instead of relying
    on implicit request/thread state.
    """

    company_filter_path = None

    def __new__(cls, related_company_field=None, *args, **kwargs):
        if cls is HorillaCompanyManager:
            cls = type(
                cls.__name__,
                (cls,),
                {"company_filter_path": related_company_field},
            )
        return super().__new__(cls)

    def __init__(self, related_company_field=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if related_company_field is not None:
            self.company_filter_path = related_company_field

    def _resolve_related_field(self, model, part):
        try:
            return model._meta.get_field(part)
        except FieldDoesNotExist:
            pass
        for rel in model._meta.related_objects:
            if rel.get_accessor_name() == part:
                return rel
        raise FieldDoesNotExist(part)

    def _field_exists(self, path):
        model = self.model
        parts = path.split("__")
        for i, part in enumerate(parts):
            try:
                field = self._resolve_related_field(model, part)
            except FieldDoesNotExist:
                logger.exception(
                    "Invalid company filter path '%s' for model %s at '%s'",
                    path,
                    self.model.__name__,
                    part,
                )
                return False
            if (
                getattr(field, "is_relation", False)
                and field.related_model
                and i < len(parts) - 1
            ):
                model = field.related_model
            elif i < len(parts) - 1:
                logger.error(
                    "Invalid company filter path '%s' for model %s: '%s' is not relational",
                    path,
                    self.model.__name__,
                    part,
                )
                return False
        return True

    def _has_company_id_fk_or_m2m(self):
        try:
            field = self.model._meta.get_field("company_id")
            return isinstance(field, (models.ForeignKey, models.ManyToManyField))
        except FieldDoesNotExist:
            return False

    def get_company_filter_path(self):
        if self.company_filter_path and self._field_exists(self.company_filter_path):
            return self.company_filter_path
        if self._has_company_id_fk_or_m2m():
            return "company_id"
        return None

    @staticmethod
    def _strict():
        return bool(getattr(settings, "TENANT_FAIL_CLOSED", True))

    @staticmethod
    def _include_global_null_rows():
        # Shared null-company rows are legacy behavior and are OFF by default;
        # any future shared reference data should have an explicit global model.
        return bool(getattr(settings, "TENANT_INCLUDE_GLOBAL_NULL_ROWS", False))

    def _specific_company_q(self, filter_path, company):
        q = Q(**{filter_path: company})
        if self._include_global_null_rows():
            q |= Q(**{f"{filter_path}__isnull": True})
        return q

    def _multi_company_q(self, filter_path, company_ids):
        q = Q(**{f"{filter_path}__in": list(company_ids)})
        if self._include_global_null_rows():
            q |= Q(**{f"{filter_path}__isnull": True})
        return q

    def get_queryset(self):
        qs = super().get_queryset()
        filter_path = self.get_company_filter_path()
        if not filter_path:
            return qs

        company = get_selected_company()
        request = getattr(_thread_locals, "request", None)

        if company is None:
            return qs.none() if self._strict() else qs

        if company == "all":
            # Platform/superuser context is not a break-glass grant. In strict
            # mode it must not turn an absent concrete school into an
            # unfiltered tenant query. A platform operator must enter an
            # explicit tenant context through an audited elevation path before
            # school-level personnel data becomes visible.
            if request and getattr(request, "user", None) and request.user.is_superuser:
                return qs.none() if self._strict() else qs

            filter_ids = None
            if request:
                filter_ids = getattr(request, "all_my_company_ids", None)
                if filter_ids is None:
                    filter_ids = getattr(request, "allowed_company_ids", None)
            if filter_ids is None:
                return qs.none() if self._strict() else qs
            if not filter_ids:
                return qs.none()
            try:
                return qs.filter(self._multi_company_q(filter_path, filter_ids)).distinct()
            except Exception as exc:
                logger.exception(
                    "Tenant union filter failed for %s path=%s: %s",
                    self.model.__name__,
                    filter_path,
                    exc,
                )
                return qs.none()

        try:
            return qs.filter(self._specific_company_q(filter_path, company)).distinct()
        except Exception as exc:
            logger.exception(
                "Tenant filter failed for %s path=%s company=%s: %s",
                self.model.__name__,
                filter_path,
                company,
                exc,
            )
            return qs.none()

    def _get_is_active_filter(self):
        request = getattr(_thread_locals, "request", None)
        raw = request.GET.get("is_active", True) if request else True
        return raw not in ["False", "false", False]

    def all(self):
        queryset = self.get_queryset()
        request = getattr(_thread_locals, "request", None)
        if not request:
            return queryset

        try:
            model_name = queryset.model._meta.model_name
            if model_name == "employee":
                queryset = queryset.filter(is_active=self._get_is_active_filter())
            elif model_name == "offboardingemployee":
                return queryset
            else:
                model_fields = queryset.model._meta.fields
                model_field_names = {f.name for f in model_fields}
                if "is_active" in model_field_names:
                    queryset = queryset.filter(is_active=self._get_is_active_filter())
                try:
                    employee_model = apps.get_model("employee", "Employee")
                    if "employee_id" in model_field_names:
                        queryset = queryset.filter(employee_id__is_active=True)
                    else:
                        for field in model_fields:
                            if (
                                isinstance(field, models.ForeignKey)
                                and field.related_model is employee_model
                            ):
                                if field.null:
                                    queryset = queryset.filter(
                                        Q(**{f"{field.name}__isnull": True})
                                        | Q(**{f"{field.name}__is_active": True})
                                    )
                                else:
                                    queryset = queryset.filter(
                                        **{f"{field.name}__is_active": True}
                                    )
                                break
                except LookupError:
                    pass
        except Exception as exc:
            logger.error(exc)
        return queryset

    def entire(self):
        """Explicit unscoped escape hatch for controlled admin/migration code only."""
        return super().get_queryset()
