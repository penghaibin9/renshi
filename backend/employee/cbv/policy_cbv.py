"""
Policy  forms
"""

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _

from employee.filters import PolicyFilter
from employee.forms import PolicyForm
from employee.models import Policy
from horilla.methods import handle_no_permission
from horilla_views.cbv_methods import login_required
from horilla_views.generic.cbv.views import HorillaFormView, HorillaNavView


@method_decorator(login_required, name="dispatch")
class PolicyFormView(HorillaFormView):
    """
    form view for create policy
    """

    form_class = PolicyForm
    model = Policy
    new_display_title = _("Policy Creation")

    def dispatch(self, request, *args, **kwargs):
        permission = (
            "employee.change_policy"
            if kwargs.get("pk")
            else "employee.add_policy"
        )
        if not request.user.has_perm(permission):
            return handle_no_permission(request)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.form.instance.pk:
            self.form_class.verbose_name = _("Policy Update")
        return context

    def form_valid(self, form: PolicyForm) -> HttpResponse:
        if form.is_valid():
            if form.instance.pk:
                message = _("Policy updated")
            else:
                message = _("Policy saved")
            with transaction.atomic():
                form.save()
            messages.success(self.request, _(message))
            return self.HttpResponse(targets_to_reload=["#policyContainerReload"])

        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
class PoliciesNav(HorillaNavView):
    """
    Policies Nav
    """

    nav_title = _("Policies")
    search_url = reverse_lazy("search-policies")
    search_swap_target = "#policyContainer"
    template_name = "generic/inline_nav.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.request.user.has_perm("employee.add_policy"):
            self.create_attrs = f"""
                data-toggle="oh-modal-toggle"
                data-target="#genericModal"
                hx-get="{reverse_lazy('create-policy')}"
                hx-target="#genericModalBody"
            """
