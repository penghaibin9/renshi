"""
views.py

This module contains the view functions for handling HTTP requests and rendering
responses in your application.

Each view function corresponds to a specific URL route and performs the necessary
actions to handle the request, process data, and generate a response.

This module is part of the recruitment project and is intended to
provide the main entry points for interacting with the application's functionality.
"""

import contextlib
import json
import logging
import os
import random
import secrets
from datetime import date
from email.mime.image import MIMEImage
from urllib.parse import parse_qs

from django import template
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as __
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST

from base.backends import ConfiguredEmailBackend
from base.methods import (
    closest_numbers,
    generate_pdf,
    get_key_instances,
    get_pagination,
    sortby,
)
from base.models import HorillaMailTemplate, JobPosition
from employee.models import Employee, EmployeeBankDetails, EmployeeWorkInformation
from horilla import settings
from horilla.decorators import (
    hx_request_required,
    login_required,
    permission_required,
)
from horilla.group_by import group_by_queryset as general_group_by
from horilla.http.response import HorillaRedirect
from horilla_auth.models import HorillaUser
from horilla_documents.models import Document
from notifications.signals import notify
from onboarding.decorators import (
    all_manager_can_enter,
    recruitment_manager_can_enter,
    stage_manager_can_enter,
)
from onboarding.filters import OnboardingCandidateFilter, OnboardingStageFilter
from onboarding.forms import (
    BankDetailsCreationForm,
    EmployeeCreationForm,
    OnboardingCandidateForm,
    OnboardingTaskForm,
    OnboardingViewStageForm,
    OnboardingViewTaskForm,
    UserCreationForm,
)
from onboarding.models import (
    CandidateStage,
    CandidateTask,
    OnboardingPortal,
    OnboardingStage,
    OnboardingTask,
    onboarding_portal_token_digest,
)
from recruitment.filters import CandidateFilter, CandidateReGroup, RecruitmentFilter
from recruitment.forms import RejectedCandidateForm
from recruitment.models import Candidate, Recruitment, RejectedCandidate
from recruitment.pipeline_grouper import group_by_queryset

logger = logging.getLogger(__name__)

_TASK_STATUSES = frozenset({"todo", "scheduled", "ongoing", "stuck", "done"})
_OFFER_STATUSES = frozenset({"not_sent", "sent", "accepted", "rejected", "joined"})
_MAX_BULK_IDS = 500


def _parse_json_id_list(raw_value):
    if raw_value is None:
        raise ValueError("invalid id list")
    try:
        values = json.loads(raw_value)
    except (TypeError, ValueError):
        raise ValueError("invalid id list") from None
    if not isinstance(values, list) or len(values) > _MAX_BULK_IDS:
        raise ValueError("invalid id list")

    normalized = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError("invalid id list") from None
        if parsed <= 0:
            raise ValueError("invalid id list")
        if parsed not in normalized:
            normalized.append(parsed)
    return normalized


def _parse_sequence_map(raw_value):
    try:
        values = json.loads(raw_value or "")
    except (TypeError, ValueError):
        raise ValueError("invalid sequence") from None
    if not isinstance(values, dict) or not values or len(values) > _MAX_BULK_IDS:
        raise ValueError("invalid sequence")
    sequence_map = {}
    for raw_id, raw_sequence in values.items():
        try:
            object_id = int(raw_id)
            sequence = int(raw_sequence)
        except (TypeError, ValueError):
            raise ValueError("invalid sequence") from None
        if object_id <= 0 or sequence < 0:
            raise ValueError("invalid sequence")
        sequence_map[object_id] = sequence
    if len(set(sequence_map.values())) != len(sequence_map):
        raise ValueError("invalid sequence")
    return sequence_map


def _can_manage_recruitment(request, recruitment, permission):
    actor = request.user.employee_get
    return request.user.has_perm(permission) or recruitment.recruitment_managers.filter(
        pk=actor.pk
    ).exists()


def _can_manage_stage(request, stage, permission):
    actor = request.user.employee_get
    return (
        request.user.has_perm(permission)
        or stage.employee_id.filter(pk=actor.pk).exists()
        or stage.recruitment_id.recruitment_managers.filter(pk=actor.pk).exists()
    )


def _can_manage_task(request, task, permission):
    actor = request.user.employee_get
    return (
        request.user.has_perm(permission)
        or task.employee_id.filter(pk=actor.pk).exists()
        or task.stage_id_id is not None
        and (
            task.stage_id.employee_id.filter(pk=actor.pk).exists()
            or task.stage_id.recruitment_id.recruitment_managers.filter(
                pk=actor.pk
            ).exists()
        )
    )


def _notify_after_commit(sender, **kwargs):
    def send_notification():
        with contextlib.suppress(Exception):
            notify.send(sender, **kwargs)

    transaction.on_commit(send_notification)


@transaction.atomic
def _ensure_candidate_onboarding_stage(candidate):
    """Create the candidate's initial onboarding stage exactly once."""
    recruitment = Recruitment.objects.select_for_update().get(
        pk=candidate.recruitment_id_id
    )
    stage = recruitment.onboarding_stage.order_by("sequence", "pk").first()
    if stage is None:
        stage = OnboardingStage.objects.create(
            recruitment_id=recruitment,
            stage_title="Initial",
            sequence=0,
        )
    candidate_stage, _created = CandidateStage.objects.get_or_create(
        candidate_id=candidate,
        defaults={"onboarding_stage_id": stage},
    )
    if (
        candidate_stage.onboarding_stage_id.recruitment_id_id
        != candidate.recruitment_id_id
    ):
        raise ValueError("candidate onboarding stage belongs to another recruitment")
    return candidate_stage


@login_required
@hx_request_required
@recruitment_manager_can_enter("onboarding.add_onboardingstage")
def stage_creation(request, obj_id):
    """
    function used to create onboarding stage.

    Parameters:
    request (HttpRequest): The HTTP request object.
    obj_id : recruitment id

    Returns:
    GET : return onboarding stage creation form template
    POST : return stage save function
    """
    form = OnboardingViewStageForm()
    if request.method == "POST":
        recruitment = Recruitment.objects.get(id=obj_id)
        form = OnboardingViewStageForm(request.POST)
        if form.is_valid():
            stage_obj = form.save()
            stage_obj.employee_id.set(
                Employee.objects.filter(id__in=form.data.getlist("employee_id"))
            )
            return stage_save(form, recruitment, request, obj_id)
    return render(request, "onboarding/stage_form.html", {"form": form, "id": obj_id})


def stage_save(form, recruitment, request, rec_id):
    """
    function used to save onboarding stage.

    Parameters:
    request (HttpRequest): The HTTP request object.
    recruitment : recruitment object
    rec_id : recruitment id

    Returns:
    GET : return onboarding view
    """
    stage = form.save(commit=False)
    stage.recruitment_id = recruitment
    stage.save()
    messages.success(request, _("New stage created successfully.."))
    users = [employee.employee_user_id for employee in stage.employee_id.all()]
    notify.send(
        request.user.employee_get,
        recipient=users,
        verb="You are chosen as onboarding stage manager",
        verb_ar="لقد تم اختيارك كمدير مرحلة التدريب.",
        verb_de="Sie wurden als Onboarding-Stage-Manager ausgewählt.",
        verb_es="Ha sido seleccionado/a como responsable de etapa de incorporación.",
        verb_fr="Vous avez été choisi(e) en tant que responsable de l'étape d'intégration.",
        icon="people-circle",
        redirect=reverse("onboarding-view"),
    )
    response = render(
        request, "onboarding/stage_form.html", {"form": form, "id": rec_id}
    )
    return HttpResponse(
        response.content.decode("utf-8") + "<script>location.reload();</script>"
    )


@login_required
@hx_request_required
@recruitment_manager_can_enter("onboarding.change_onboardingstage")
def stage_update(request, stage_id, recruitment_id):
    """
    function used to update onboarding stage.

    Parameters:
    request (HttpRequest): The HTTP request object.
    stage_id : stage id
    recruitment_id : recruitment id

    Returns:
    GET : return onboarding stage update form template
    POST : return onboarding view
    """
    onboarding_stage = OnboardingStage.objects.get(id=stage_id)
    form = OnboardingViewStageForm(instance=onboarding_stage)
    if request.method == "POST":
        form = OnboardingViewStageForm(request.POST, instance=onboarding_stage)
        if form.is_valid():
            stage = form.save()
            stage.employee_id.set(
                Employee.objects.filter(id__in=form.data.getlist("employee_id"))
            )
            messages.success(request, _("Stage is updated successfully.."))
            users = [employee.employee_user_id for employee in stage.employee_id.all()]
            notify.send(
                request.user.employee_get,
                recipient=users,
                verb="You are chosen as onboarding stage manager",
                verb_ar="لقد تم اختيارك كمدير مرحلة التدريب.",
                verb_de="Sie wurden als Onboarding-Stage-Manager ausgewählt.",
                verb_es="Ha sido seleccionado/a como responsable de etapa de incorporación.",
                verb_fr="Vous avez été choisi(e) en tant que responsable de l'étape d'intégration.",
                icon="people-circle",
                redirect=reverse("onboarding-view"),
            )
            if request.META.get("HTTP_HX_REQUEST") == "true":
                return HttpResponse(
                    """
                    <script>
                      (function () {
                        const activeTab = document.querySelector(".oh-tabs__tab--active");
                        const target = activeTab ? activeTab.getAttribute("data-target") : null;
                        if (target && window.htmx) {
                          htmx.ajax("GET", window.location.href, {
                            target: target,
                            swap: "outerHTML",
                            select: target
                          });
                        }
                        $("#reloadMessagesButton").click();
                        $("#genericModal").removeClass("oh-modal--show");
                      })();
                    </script>
                    """
                )
            return HorillaRedirect(request)
    return render(
        request,
        "onboarding/stage_update.html",
        {"form": form, "stage_id": stage_id, "recruitment_id": recruitment_id},
    )


@login_required
@recruitment_manager_can_enter("onboarding.change_onboardingstage")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def update_stage_order(request, pk):
    """
    This method is used to update the stage sequence of the onboarding
    """
    recruitment = Recruitment.find(pk)
    if not recruitment:
        return HorillaRedirect(request, message=_("Recruitment not found."))
    if not _can_manage_recruitment(
        request, recruitment, "onboarding.change_onboardingstage"
    ):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)

    if request.method == "GET":
        stages = recruitment.onboarding_stage.order_by("sequence", "pk")
        return render(
            request,
            "cbv/pipeline/onboarding/stage_order.html",
            {"recruitment": recruitment, "stages": stages},
        )

    try:
        order = _parse_json_id_list(request.POST.get("order"))
    except ValueError:
        return JsonResponse({"status": "error", "message": _("Invalid stage order.")}, status=400)
    stages = {
        stage.pk: stage
        for stage in recruitment.onboarding_stage.select_for_update().filter(pk__in=order)
    }
    if len(stages) != len(order):
        return JsonResponse({"status": "error", "message": _("Invalid stage order.")}, status=400)
    ordered_stages = []
    for index, stage_id in enumerate(order):
        stage = stages[stage_id]
        stage.sequence = index + 1
        ordered_stages.append(stage)
    OnboardingStage.objects.bulk_update(ordered_stages, ["sequence"])
    messages.success(request, _("Sequence Updated Successfully"))
    return JsonResponse({"status": "success"})


@login_required
@recruitment_manager_can_enter("onboarding.delete_onboardingstage")
@require_POST
@transaction.atomic
def stage_delete(request, stage_id):
    """
    function used to delete onboarding stage.

    Parameters:
    request (HttpRequest): The HTTP request object.
    stage_id : stage id

    Returns:
    GET : return onboarding view
    """
    try:
        stage = (
            OnboardingStage.objects.select_for_update()
            .select_related("recruitment_id")
            .get(id=stage_id)
        )
        if not _can_manage_recruitment(
            request, stage.recruitment_id, "onboarding.delete_onboardingstage"
        ):
            return JsonResponse(
                {"message": _("You do not have permission.")}, status=403
            )
        stage.delete()
        messages.success(request, _("The stage deleted successfully..."))

    except OnboardingStage.DoesNotExist:
        messages.error(request, _("Stage not found."))
    except ProtectedError:
        transaction.set_rollback(True)
        messages.error(request, _("There are candidates in this stage..."))
    return HorillaRedirect(request)


@login_required
@hx_request_required
@stage_manager_can_enter("onboarding.add_onboardingtask")
@transaction.atomic
def task_creation(request):
    """
    function used to create onboarding task.

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return onboarding task creation form template
    POST : return onboarding view
    """
    stage_id = request.GET.get("stage_id")
    stage = (
        OnboardingStage.objects.select_for_update()
        .select_related("recruitment_id")
        .get(id=stage_id)
    )
    if not _can_manage_stage(request, stage, "onboarding.add_onboardingtask"):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)
    form = OnboardingViewTaskForm(initial={"stage_id": stage})

    if request.method == "POST":
        form_data = OnboardingViewTaskForm(request.POST, initial={"stage_id": stage})
        if form_data.is_valid():
            candidates = form_data.cleaned_data["candidates"]
            stage_id = form_data.cleaned_data["stage_id"]
            managers = form_data.cleaned_data["managers"]
            title = form_data.cleaned_data["task_title"]
            is_required = form_data.cleaned_data["is_required"]
            if stage_id is None or stage_id.pk != stage.pk or any(
                candidate.recruitment_id_id != stage.recruitment_id_id
                for candidate in candidates
            ):
                return JsonResponse(
                    {"message": _("Task assignment scope is invalid.")}, status=400
                )
            onboarding_task = OnboardingTask(
                task_title=title, stage_id=stage_id, is_required=is_required
            )
            onboarding_task.save()
            onboarding_task.employee_id.set(managers)
            onboarding_task.candidates.set(candidates)
            CandidateTask.objects.bulk_create(
                [
                    CandidateTask(
                        candidate_id=candidate,
                        stage_id=stage_id,
                        onboarding_task_id=onboarding_task,
                    )
                    for candidate in candidates
                ]
            )
            users = [
                manager.employee_user_id
                for manager in onboarding_task.employee_id.all()
            ]
            _notify_after_commit(
                request.user.employee_get,
                recipient=users,
                verb="You are chosen as an onboarding task manager",
                verb_ar="لقد تم اختيارك كمدير مهام التدريب.",
                verb_de="Sie wurden als Onboarding-Aufgabenmanager ausgewählt.",
                verb_es="Ha sido seleccionado/a como responsable de tareas de incorporación.",
                verb_fr="Vous avez été choisi(e) en tant que responsable des tâches d'intégration.",
                icon="people-circle",
                redirect=reverse("onboarding-view"),
            )
            messages.success(request, _("New task created successfully..."))
            return HorillaRedirect(request)
    return render(
        request, "onboarding/task_form.html", {"form": form, "stage_id": stage_id}
    )


@login_required
@hx_request_required
@stage_manager_can_enter("onboarding.change_onboardingtask")
@transaction.atomic
def task_update(
    request,
    task_id,
):
    """
    function used to update onboarding task.

    Parameters:
    request (HttpRequest): The HTTP request object.
    task_id : task id

    Returns:
    GET : return onboarding task update form template
    POST : return onboarding view
    """
    onboarding_task = (
        OnboardingTask.objects.select_for_update()
        .select_related("stage_id__recruitment_id")
        .get(id=task_id)
    )
    if not _can_manage_task(
        request, onboarding_task, "onboarding.change_onboardingtask"
    ):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)
    form = OnboardingTaskForm(instance=onboarding_task)
    if request.method == "POST":
        form = OnboardingTaskForm(request.POST, instance=onboarding_task)
        if form.is_valid():
            selected_stage = form.cleaned_data["stage_id"]
            selected_candidates = list(form.cleaned_data["candidates"])
            if selected_stage is None or not _can_manage_stage(
                request, selected_stage, "onboarding.change_onboardingtask"
            ) or any(
                candidate.recruitment_id_id != selected_stage.recruitment_id_id
                for candidate in selected_candidates
            ):
                return JsonResponse(
                    {"message": _("Task assignment scope is invalid.")}, status=400
                )
            task = form.save()
            task.employee_id.set(
                Employee.objects.filter(id__in=form.data.getlist("employee_id"))
            )
            selected_candidate_ids = {
                candidate.pk for candidate in selected_candidates
            }
            candidate_tasks = list(
                CandidateTask.objects.select_for_update().filter(
                    onboarding_task_id=task
                )
            )
            CandidateTask.objects.filter(
                onboarding_task_id=task
            ).exclude(candidate_id_id__in=selected_candidate_ids).delete()
            retained_ids = {
                candidate_task.candidate_id_id
                for candidate_task in candidate_tasks
                if candidate_task.candidate_id_id in selected_candidate_ids
            }
            retained_tasks = [
                candidate_task
                for candidate_task in candidate_tasks
                if candidate_task.candidate_id_id in selected_candidate_ids
            ]
            for candidate_task in retained_tasks:
                candidate_task.stage_id = selected_stage
            CandidateTask.objects.bulk_update(retained_tasks, ["stage_id"])
            CandidateTask.objects.bulk_create(
                [
                    CandidateTask(
                        candidate_id=candidate,
                        stage_id=selected_stage,
                        onboarding_task_id=task,
                    )
                    for candidate in selected_candidates
                    if candidate.pk not in retained_ids
                ]
            )
            messages.success(request, _("Task updated successfully.."))
            users = [employee.employee_user_id for employee in task.employee_id.all()]
            _notify_after_commit(
                request.user.employee_get,
                recipient=users,
                verb="You are chosen as an onboarding task manager",
                verb_ar="لقد تم اختيارك كمدير مهام التدريب.",
                verb_de="Sie wurden als Onboarding-Aufgabenmanager ausgewählt.",
                verb_es="Ha sido seleccionado/a como responsable de tareas de incorporación.",
                verb_fr="Vous avez été choisi(e) en tant que responsable des tâches d'intégration.",
                icon="people-circle",
                redirect=reverse("onboarding-view"),
            )
            return HorillaRedirect(request)
    return render(
        request,
        "onboarding/task_update.html",
        {
            "form": form,
            "task_id": task_id,
        },
    )


@login_required
@stage_manager_can_enter("onboarding.delete_onboardingtask")
@require_POST
@transaction.atomic
def task_delete(request, task_id):
    """
    function used to delete onboarding task.

    Parameters:
    request (HttpRequest): The HTTP request object.
    task_id : task id


    Returns:
    GET : return onboarding view
    """
    try:
        task = (
            OnboardingTask.objects.select_for_update()
            .select_related("stage_id__recruitment_id")
            .get(id=task_id)
        )
        if not _can_manage_task(
            request, task, "onboarding.delete_onboardingtask"
        ):
            return JsonResponse(
                {"message": _("You do not have permission.")}, status=403
            )
        task.delete()
        messages.success(request, _("The task deleted successfully..."))
    except OnboardingTask.DoesNotExist:
        messages.error(request, _("Task not found."))
    except ProtectedError:
        transaction.set_rollback(True)
        messages.error(
            request,
            _(
                "You cannot delete this task because some candidates are associated with it."
            ),
        )
    return redirect(onboarding_view)


@login_required
@permission_required("recruitment.add_candidate")
@transaction.atomic
def candidate_creation(request):
    """
    function used to create hired candidates .

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return candidate creation form template
    POST : return candidate view
    """
    form = OnboardingCandidateForm()
    if request.method == "POST":
        form = OnboardingCandidateForm(request.POST, request.FILES)
        if form.is_valid():
            candidate = form.save()
            candidate.hired = True
            candidate.save(update_fields=["hired"])
            _ensure_candidate_onboarding_stage(candidate)
            messages.success(request, _("New candidate created successfully.."))
            return redirect(candidates_view)
    return render(request, "onboarding/candidate_creation.html", {"form": form})


@login_required
@permission_required("recruitment.change_candidate")
def candidate_update(request, obj_id):
    """
    function used to update hired candidates .

    Parameters:
    request (HttpRequest): The HTTP request object.
    obj_id : recruitment id

    Returns:
    GET : return candidate update form template
    POST : return candidate view
    """
    candidate = Candidate.find(obj_id)
    if not candidate:
        return HorillaRedirect(request, message=_("Candidate not found."))
    form = OnboardingCandidateForm(instance=candidate)
    if request.method == "POST":
        form = OnboardingCandidateForm(request.POST, request.FILES, instance=candidate)
        if form.is_valid():
            form.save()
            messages.success(request, _("Candidate detail is updated successfully.."))
            return redirect(candidates_view)
    return render(request, "onboarding/candidate_update.html", {"form": form})


@login_required
@permission_required("onboarding.delete_onboardingcandidate")
@require_POST
@transaction.atomic
def candidate_delete(request, obj_id):
    """
    function used to delete hired candidates .

    Parameters:
    request (HttpRequest): The HTTP request object.
    obj_id : candidate id

    Returns:
    GET : return candidate view
    """
    try:
        Candidate.objects.select_for_update().get(id=obj_id).delete()
        messages.success(request, _("Candidate deleted successfully.."))
    except Candidate.DoesNotExist:
        messages.error(request, _("Candidate not found."))
    except ProtectedError as e:
        transaction.set_rollback(True)
        models_verbose_name_sets = set()
        for obj in e.protected_objects:
            models_verbose_name_sets.add(__(obj._meta.verbose_name))
        models_verbose_name_str = (", ").join(models_verbose_name_sets)
        messages.error(
            request,
            _(
                "You cannot delete this candidate. The candidate is included in the {}".format(
                    models_verbose_name_str
                )
            ),
        )
    if request.META.get("HTTP_HX_REQUEST"):
        return HttpResponse(status=204)
    return redirect(reverse("candidates-view"))


@login_required
@hx_request_required
@all_manager_can_enter("onboarding.view_candidatestage")
def candidates_single_view(request, id, **kwargs):
    """
    Candidate individual view for the onboarding candidates
    """
    candidate = Candidate.objects.get(id=id)
    if not CandidateStage.objects.filter(candidate_id=candidate).exists():
        return JsonResponse(
            {"message": _("Candidate onboarding has not been initialized.")},
            status=409,
        )

    recruitment = candidate.recruitment_id
    choices = CandidateTask.choice
    context = {
        "recruitment": recruitment,
        "choices": choices,
        "candidate": candidate,
        "single_view": True,
    }

    requests_ids_json = request.GET.get("requests_ids")
    if requests_ids_json:
        requests_ids = json.loads(requests_ids_json)
        previous_id, next_id = closest_numbers(requests_ids, id)
        context["requests_ids"] = requests_ids_json
        context["previous"] = previous_id
        context["next"] = next_id
    return render(
        request,
        "onboarding/single_view.html",
        context,
    )


def paginator_qry(qryset, page_number):
    """
    function used to paginate query set
    """
    paginator = Paginator(qryset, get_pagination())
    qryset = paginator.get_page(page_number)
    return qryset


@login_required
@permission_required(perm="onboarding.view_onboardingcandidate")
def candidates_view(request):
    """
    function used to view hired candidates .

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return candidate view  template
    """
    queryset = Candidate.objects.filter(
        is_active=True,
        hired=True,
        recruitment_id__closed=False,
    )
    candidate_filter_obj = CandidateFilter(request.GET, queryset)
    previous_data = request.GET.urlencode()
    page_number = request.GET.get("page")
    page_obj = paginator_qry(candidate_filter_obj.qs, page_number)
    mail_templates = HorillaMailTemplate.objects.all()
    data_dict = parse_qs(previous_data)
    get_key_instances(Candidate, data_dict)
    return render(
        request,
        "onboarding/candidates_view.html",
        {
            "candidates": page_obj,
            "form": candidate_filter_obj.form,
            "pd": previous_data,
            "gp_fields": CandidateReGroup.fields,
            "mail_templates": mail_templates,
            "hired_candidates": queryset,
            "filter_dict": data_dict,
        },
    )


@login_required
@hx_request_required
@permission_required(perm="recruitment.view_candidate")
def hired_candidate_view(request):
    previous_data = request.GET.urlencode()
    candidates = Candidate.objects.filter(
        hired=True,
        recruitment_id__closed=False,
    )
    if request.GET.get("is_active") is None:
        candidates = candidates.filter(is_active=True)
    candidates = CandidateFilter(request.GET, queryset=candidates).qs
    return render(
        request,
        "candidate/candidate_card.html",
        {
            "data": paginator_qry(candidates, request.GET.get("page")),
            "pd": previous_data,
        },
    )


@login_required
@hx_request_required
@permission_required(perm="onboarding.view_onboardingcandidate")
def candidate_filter(request):
    """
    function used to filter hired candidates .

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return candidate view template
    """
    queryset = Candidate.objects.filter(
        is_active=True,
        hired=True,
        recruitment_id__closed=False,
    )
    candidates = CandidateFilter(request.GET, queryset).qs
    previous_data = request.GET.urlencode()
    page_number = request.GET.get("page")
    data_dict = parse_qs(previous_data)
    get_key_instances(Candidate, data_dict)
    candidates = sortby(request, candidates, "orderby")
    field = request.GET.get("field")
    template = "onboarding/candidates.html"
    if field != "" and field is not None:
        template = "onboarding/group_by.html"
        candidates = general_group_by(
            candidates, field, request.GET.get("page"), "page"
        )
    page_obj = paginator_qry(candidates, page_number)
    return render(
        request,
        template,
        {"candidates": page_obj, "pd": previous_data, "filter_dict": data_dict},
    )


@login_required
@all_manager_can_enter("recruitment.view_recruitment")
@require_POST
def email_send(request):
    host = request.get_host()
    protocol = "https" if request.is_secure() else "http"

    candidates = request.POST.getlist("ids")
    other_attachments = request.FILES.getlist("other_attachments")
    template_attachment_ids = request.POST.getlist("template_attachment_ids")

    email_backend = ConfiguredEmailBackend()
    display_email_name = email_backend.dynamic_from_email_with_display_name

    if not candidates:
        messages.info(request, _("Please choose candidates"))
        return HorillaRedirect(request)

    # Fetch PDF templates
    bodys = list(
        HorillaMailTemplate.objects.filter(id__in=template_attachment_ids).values_list(
            "body", flat=True
        )
    )

    # Collect uploaded attachments
    attachments_other = []
    for file in other_attachments:
        attachments_other.append((file.name, file.read(), file.content_type))
        file.close()

    for cand_id in candidates:
        candidate = Candidate.objects.get(id=cand_id)
        attachments = list(attachments_other)

        # Prevent duplicate onboarding
        if candidate.converted_employee_id:
            messages.info(
                request,
                _("%(candidate)s has already been converted to employee.")
                % {"candidate": candidate},
            )
            continue

        try:
            _ensure_candidate_onboarding_stage(candidate)
        except Exception as exc:
            logger.error(
                "Onboarding stage initialization failed candidate_id=%s error_type=%s",
                candidate.pk,
                type(exc).__name__,
            )
            messages.error(
                request,
                _("Unable to initialize onboarding for %(candidate)s.")
                % {"candidate": candidate.name},
            )
            continue

        # Generate PDFs
        for html in bodys:
            template_bdy = template.Template(html)
            context = template.Context(
                {"instance": candidate, "self": request.user.employee_get}
            )
            render_bdy = template_bdy.render(context)

            attachments.append(
                (
                    "Document.pdf",
                    generate_pdf(render_bdy, {}, path=False, title="Document").content,
                    "application/pdf",
                )
            )

        # Rotate the bearer token without destroying a partially completed
        # onboarding state. Re-sending an invitation must work across workers
        # and must not send the candidate back to step zero.
        token = secrets.token_hex(15)
        portal, portal_created = OnboardingPortal.objects.get_or_create(
            candidate_id=candidate,
            defaults={"token": token},
        )
        previous_portal_state = {
            "token": portal.token,
            "used": portal.used,
        }
        if not portal_created:
            portal.token = token
        portal.used = False
        portal.save(update_fields=["token", "used"])

        # Render email HTML
        html_message = render_to_string(
            "onboarding/mail_templates/default.html",
            {
                "portal": f"{protocol}://{host}/onboarding/user-creation/{token}",
                "instance": candidate,
                "host": host,
                "protocol": protocol,
                "use_cid_logo": True,
            },
            request=request,
        )

        # ✅ Use EmailMultiAlternatives (IMPORTANT)
        email = EmailMultiAlternatives(
            subject=f"Hello {candidate.name}, Congratulations on your selection!",
            body=html_message,
            from_email=display_email_name,
            to=[candidate.email],
            reply_to=[display_email_name],
        )

        email.attach_alternative(html_message, "text/html")

        # Attach files
        for attachment in attachments:
            email.attach(*attachment)

        # ✅ Attach company logo INLINE
        try:
            company = candidate.recruitment_id.company_id
            if company and company.icon and os.path.exists(company.icon.path):
                image_path = company.icon.path
            else:
                image_path = finders.find("images/ui/university-seal.jpg")

            if image_path:
                with open(image_path, "rb") as f:
                    logo = MIMEImage(f.read())
                    logo.add_header("Content-ID", "<company_logo>")
                    logo.add_header(
                        "Content-Disposition",
                        "inline",
                        filename=os.path.basename(image_path),
                    )
                    email.attach(logo)
        except Exception as exc:
            logger.warning(
                "Company logo attachment skipped error_type=%s", type(exc).__name__
            )

        # Send mail
        try:
            sent_count = email.send(fail_silently=False)
            if sent_count != 1:
                raise RuntimeError("mail backend returned a non-success count")
            messages.success(request, _("Portal link sent to the candidate"))
        except Exception as exc:
            # A failed re-send must not invalidate the candidate's previous
            # working link. Newly created, undelivered portals are disabled.
            if portal_created:
                portal.used = True
                portal.save(update_fields=["used"])
            else:
                portal.token = previous_portal_state["token"]
                portal.used = previous_portal_state["used"]
                portal.save(update_fields=["token", "used"])
            logger.error(
                "Onboarding invitation delivery failed candidate_id=%s error_type=%s",
                candidate.pk,
                type(exc).__name__,
            )
            messages.error(
                request,
                _("Mail not sent to %(candidate_name)s")
                % {"candidate_name": candidate.name},
            )
            continue

        # Mark onboarding started without triggering Candidate.save() validation
        # (which can fail with "Choose valid choice" on job_position_id when the
        # candidate's job position has been removed from recruitment.open_positions).
        Candidate.objects.filter(pk=candidate.pk).update(start_onboard=True)
        candidate.start_onboard = True

    return HorillaRedirect(request)


def onboarding_query_grouper(request, queryset):
    """
    This method is used to make group of the onboarding records
    """
    groups = []
    for rec in queryset:
        employees = []
        stages = OnboardingStageFilter(
            request.GET, queryset=rec.onboarding_stage.all()
        ).qs.order_by("sequence")
        all_stages_grouper = []
        data = {"recruitment": rec, "stages": []}
        for stage in stages:
            all_stages_grouper.append({"grouper": stage, "list": []})
            stage_candidates = OnboardingCandidateFilter(
                request.GET,
                stage.candidate.filter(
                    candidate_id__is_active=True,
                ),
            ).qs.order_by("sequence")

            page_name = "page" + stage.stage_title + str(rec.id)
            grouper = group_by_queryset(
                stage_candidates,
                "onboarding_stage_id",
                request.GET.get(page_name),
                page_name,
            ).object_list
            data["stages"] = data["stages"] + grouper
            employees = employees + [
                employee.candidate_id.id for employee in stage.candidate.all()
            ]
        ordered_data = []
        # combining un used groups in to the grouper
        groupers = data["stages"]
        for stage in stages:
            found = False
            for grouper in groupers:
                if grouper["grouper"] == stage:
                    ordered_data.append(grouper)
                    found = True
                    break
            if not found:
                ordered_data.append({"grouper": stage})
        data = {
            "recruitment": rec,
            "stages": ordered_data,
            "employee_ids": employees,
        }
        groups.append(data)
    return groups


@login_required
@all_manager_can_enter("onboarding.view_onboardingstage")
def onboarding_view(request):
    """
    function used to view onboarding main view.

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return onboarding view template
    """
    filter_obj = RecruitmentFilter(request.GET)
    # is active filteration not providing on pipeline
    recruitments = filter_obj.qs
    if not request.user.has_perm("onboarding.view_onboardingstage"):
        recruitments = recruitments.filter(
            is_active=True, recruitment_managers__in=[request.user.employee_get]
        ) | recruitments.filter(
            onboarding_stage__employee_id__in=[request.user.employee_get]
        )
    employee_tasks = request.user.employee_get.onboarding_task.all()
    for task in employee_tasks:
        if task.stage_id and task.stage_id.recruitment_id not in recruitments:
            recruitments = recruitments | filter_obj.qs.filter(
                id=task.stage_id.recruitment_id.id
            )
    recruitments = recruitments.filter(is_active=True).distinct()
    status = request.GET.get("closed")
    if not status:
        recruitments = recruitments.filter(closed=False)

    onboarding_stages = OnboardingStage.objects.all()
    choices = CandidateTask.choice
    previous_data = request.GET.urlencode()
    paginator = Paginator(recruitments.order_by("id"), 4)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    groups = onboarding_query_grouper(request, page_obj)
    for item in groups:
        setattr(item["recruitment"], "stages", item["stages"])
        setattr(item["recruitment"], "employee_ids", item["employee_ids"])
    filter_dict = parse_qs(request.GET.urlencode())
    for key, val in filter_dict.copy().items():
        if val[0] == "unknown" or key == "view":
            del filter_dict[key]
    return render(
        request,
        "onboarding/onboarding_view.html",
        {
            "recruitments": page_obj,
            "rec_filter_obj": filter_obj,
            "onboarding_stages": onboarding_stages,
            "choices": choices,
            "filter_dict": filter_dict,
            "status": status,
            "pd": previous_data,
        },
    )


@login_required
@all_manager_can_enter("onboarding.view_onboardingstage")
def kanban_view(request):
    # filter_obj = RecruitmentFilter(request.GET)
    # # is active filteration not providing on pipeline
    # recruitments = filter_obj.qs.filter(is_active=True)
    filter_obj = RecruitmentFilter(request.GET)
    # is active filteration not providing on pipeline
    recruitments = filter_obj.qs
    if not request.user.has_perm("onboarding.view_onboardingstage"):
        recruitments = recruitments.filter(
            is_active=True, recruitment_managers__in=[request.user.employee_get]
        ) | recruitments.filter(
            onboarding_stage__employee_id__in=[request.user.employee_get]
        )
    employee_tasks = request.user.employee_get.onboarding_task.all()
    for task in employee_tasks:
        if task.stage_id and task.stage_id.recruitment_id not in recruitments:
            recruitments = recruitments | filter_obj.qs.filter(
                id=task.stage_id.recruitment_id.id
            )
    recruitments = recruitments.filter(is_active=True).distinct()

    status = request.GET.get("closed")
    if not status:
        recruitments = recruitments.filter(closed=False)

    onboarding_stages = OnboardingStage.objects.all()
    choices = CandidateTask.choice
    stage_form = OnboardingViewStageForm()

    previous_data = request.GET.urlencode()

    filter_obj = RecruitmentFilter(request.GET, queryset=recruitments)
    paginator = Paginator(recruitments, 4)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    groups = onboarding_query_grouper(request, page_obj)

    for item in groups:
        setattr(item["recruitment"], "stages", item["stages"])
    filter_dict = parse_qs(request.GET.urlencode())
    for key, val in filter_dict.copy().items():
        if val[0] == "unknown" or key == "view":
            del filter_dict[key]

    return render(
        request,
        "onboarding/kanban/kanban.html",
        {
            "recruitments": page_obj,
            "rec_filter_obj": filter_obj,
            "onboarding_stages": onboarding_stages,
            "choices": choices,
            "filter_dict": filter_dict,
            "stage_form": stage_form,
            "status": status,
            "pd": previous_data,
            "card": True,
        },
    )


def user_creation(request, token):
    """
    function used to create user account in onboarding portal.

    Parameters:
    request (HttpRequest): The HTTP request object.
    token : random generated onboarding portal token

    Returns:
    GET : return user creation form template
    POST : return user_save function
    """
    try:
        onboarding_portal = OnboardingPortal.objects.get(
            token=onboarding_portal_token_digest(token)
        )
        if onboarding_portal.used is True:
            return render(request, "404.html", status=404)
        if onboarding_portal.count >= 3:
            return redirect("employee-bank-details", token)
        if onboarding_portal.count >= 2:
            return redirect("employee-creation", token)
        if onboarding_portal.count >= 1:
            return redirect("profile-view", token)
        candidate = onboarding_portal.candidate_id
        if HorillaUser.objects.filter(username__iexact=candidate.email).exists():
            logger.warning(
                "Onboarding account creation blocked by username collision portal=%s",
                onboarding_portal.pk,
            )
            return HttpResponse(
                _("An account already exists for this email. Please contact HR."),
                status=409,
            )
        form = UserCreationForm()
        if request.method == "POST":
            form = UserCreationForm(request.POST)
            if form.is_valid():
                return user_save(form, onboarding_portal, request, token)
        return render(
            request,
            "onboarding/user_creation.html",
            {
                "form": form,
                "company": onboarding_portal.candidate_id.recruitment_id.company_id,
            },
        )
    except OnboardingPortal.DoesNotExist:
        return render(request, "404.html", status=404)
    except Exception as exc:
        # Do not serialize arbitrary database/provider exception messages into
        # logs: upstream exceptions can contain DSNs, tokens or submitted data.
        logger.error(
            "Onboarding portal user-creation failed error_type=%s",
            type(exc).__name__,
        )
        return HttpResponse(
            _("The onboarding portal is temporarily unavailable."), status=500
        )


@transaction.atomic
def user_save(form, onboarding_portal, request, token):
    """
    function used to save user.

    Parameters:
    request (HttpRequest): The HTTP request object.
    onboarding_portal : onboarding portal object
    token : random generated onboarding portal token

    Returns:
    GET : return profile view
    """
    user = form.save(commit=False)
    user.username = onboarding_portal.candidate_id.email
    user.email = onboarding_portal.candidate_id.email
    user.save()
    onboarding_portal.count = 1
    onboarding_portal.save(update_fields=["count"])
    messages.success(request, _("Account created successfully.."))
    return redirect("profile-view", token)


@transaction.atomic
def profile_view(request, token):
    """
    function used to view user profile.

    Parameters:
    request (HttpRequest): The HTTP request object.
    token : random generated onboarding portal token

    Returns:
    GET : return user profile template
    POST : update profile image of the user
    """
    onboarding_portal = OnboardingPortal.objects.filter(
        token=onboarding_portal_token_digest(token)
    ).first()
    if onboarding_portal is None or onboarding_portal.used:
        return render(request, "404.html", status=404)
    if onboarding_portal.count < 1:
        return redirect("user-creation", token)
    if onboarding_portal.count >= 2:
        return redirect("employee-creation", token)
    candidate = onboarding_portal.candidate_id
    if request.method == "POST":
        profile = request.FILES.get("profile")
        if profile is not None:
            candidate.profile = profile
            candidate.save()
            onboarding_portal.profile = profile
            onboarding_portal.count = 2
            onboarding_portal.save()
            messages.success(request, _("Profile picture updated successfully.."))
    return render(
        request,
        "onboarding/profile_view.html",
        {
            "candidate": candidate,
            "profile": onboarding_portal.profile,
            "token": token,
            "company": candidate.recruitment_id.company_id,
        },
    )


@transaction.atomic
def employee_creation(request, token):
    """
    function used to create employee.

    Parameters:
    request (HttpRequest): The HTTP request object.
    token : random generated onboarding portal token.

    Returns:
    GET : return employee creation profile template.
    POST : return employee bank detail creation template.
    """
    onboarding_portal = OnboardingPortal.objects.filter(
        token=onboarding_portal_token_digest(token)
    ).first()
    if onboarding_portal is None or onboarding_portal.used:
        return render(request, "404.html", status=404)
    if onboarding_portal.count < 1:
        return redirect("user-creation", token)
    if onboarding_portal.count >= 3:
        return redirect("employee-bank-details", token)
    candidate = onboarding_portal.candidate_id
    initial = {
        "employee_first_name": candidate.name,
        "phone": candidate.mobile,
        "address": candidate.address,
        "dob": candidate.dob,
    }
    # Persisted state is required here: process-local dictionaries break as soon
    # as consecutive requests land on different Gunicorn workers.
    user = HorillaUser.objects.filter(username=candidate.email).first()

    if user is None:
        messages.error(
            request,
            _("Please create your account first before continuing employee creation."),
        )
        return redirect("user-creation", token)

    user_email = getattr(user, "email", None) or candidate.email
    if Employee.objects.filter(email=user_email).exists():
        messages.success(request, _("Employee with email id already exists."))
        return redirect("login/")
    employee_qs = (
        Employee.objects.filter(employee_user_id=user)
        if getattr(user, "pk", None)
        else Employee.objects.none()
    )
    if employee_qs.first() is not None:
        employee = employee_qs.first()
        if employee.employee_bank_details:
            messages.success(request, _("Employee already exists.."))
            return redirect("login/")
        initial = employee.__dict__

    form = EmployeeCreationForm(
        initial=initial,
    )
    # form.errors.clear()
    if request.method == "POST":
        instance = employee_qs.first() if getattr(user, "pk", None) else None
        form = EmployeeCreationForm(
            request.POST,
            instance=instance,
        )
        if form.is_valid():
            if user is None:
                messages.error(
                    request,
                    _(
                        "User account was not found. Please complete account creation and try again."
                    ),
                )
                return redirect("user-creation", token)
            if not getattr(user, "pk", None):
                user.save()
            employee_personal_info = form.save(commit=False)
            employee_personal_info.employee_user_id = user
            employee_personal_info.email = candidate.email
            if candidate.profile and candidate.profile.storage.exists(
                candidate.profile.name
            ):  # 896
                filename = os.path.basename(candidate.profile.name)
                employee_personal_info.employee_profile.save(
                    filename, ContentFile(candidate.profile.read()), save=False
                )

            employee_personal_info.is_from_onboarding = True
            employee_personal_info.save()

            EmployeeWorkInformation.objects.update_or_create(
                employee_id=employee_personal_info,
                defaults={
                    "department_id": candidate.job_position_id.department_id,
                    "job_position_id": candidate.job_position_id,
                    "company_id": candidate.recruitment_id.company_id,
                    "date_joining": candidate.joining_date,
                    "email": candidate.email,
                },
            )

            Document.objects.bulk_create(
                [
                    Document(
                        title=doc.title,
                        employee_id=employee_personal_info,
                        document=doc.document,
                        status=doc.status,
                        reject_reason=doc.reject_reason,
                    )
                    for doc in candidate.candidatedocument_set.all()
                ]
            )

            onboarding_portal.count = 3
            onboarding_portal.save(update_fields=["count"])
            login(request, user)
            messages.success(
                request, _("Employee personal details created successfully..")
            )
            return redirect("employee-bank-details", token)
    return render(
        request,
        "onboarding/employee_creation.html",
        {"form": form, "employee": candidate.recruitment_id.company_id},
    )


def employee_bank_details(request, token):
    """
    function used to create employee bank details creation.

    Parameters:
    request (HttpRequest): The HTTP request object.
    token : random generated onboarding portal token

    Returns:
    GET : return bank details creation template
    POST : return employee_bank_details_save function
    """
    onboarding_portal = OnboardingPortal.objects.filter(
        token=onboarding_portal_token_digest(token)
    ).first()
    if onboarding_portal is None or onboarding_portal.used:
        return render(request, "404.html", status=404)
    if onboarding_portal.count < 3:
        return redirect("employee-creation", token)

    user = HorillaUser.objects.filter(
        username=onboarding_portal.candidate_id.email
    ).first()
    employee = Employee.objects.filter(employee_user_id=user).first()
    bank_info = EmployeeBankDetails.objects.filter(employee_id=employee).first()
    form = BankDetailsCreationForm(instance=bank_info)
    if request.method == "POST":
        form = BankDetailsCreationForm(
            request.POST,
            instance=bank_info,
        )
        if form.is_valid():
            return employee_bank_details_save(form, request, onboarding_portal)
    return render(
        request,
        "onboarding/employee_bank_details.html",
        {
            "form": form,
            "company": onboarding_portal.candidate_id.recruitment_id.company_id,
        },
    )


@transaction.atomic
def employee_bank_details_save(form, request, onboarding_portal):
    """
    function used to save employee bank details.

    Parameters:
    request (HttpRequest): The HTTP request object.
    form : Form object.
    onboarding_portal : Onboarding portal object.

    Returns:
    GET : return welcome onboard view
    """
    employee_bank_detail = form.save(commit=False)
    employee = Employee.objects.get(employee_user_id=request.user)
    employee_bank_detail.employee_id = employee
    candidate = onboarding_portal.candidate_id
    candidate.converted_employee_id = employee
    candidate.save()
    employee_bank_detail.save()
    onboarding_portal.count = 4
    onboarding_portal.used = True
    onboarding_portal.save()
    messages.success(request, _("Employee bank details created successfully.."))
    return redirect(welcome_aboard)


@login_required
def welcome_aboard(request):
    """
    function used to view welcome aboard.

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return welcome onboard view
    """
    return render(request, "onboarding/welcome_aboard.html")


@login_required
@require_http_methods(["POST"])
@all_manager_can_enter("onboarding.change_candidatetask")
@transaction.atomic
def candidate_task_update(request, taskId):
    """
    function used to update candidate task.

    Parameters:
    request (HttpRequest): The HTTP request object.
    obj_id : candidate task id

    Returns:
    POST : return candidate task template
    """
    status = request.POST.get("status")
    if status not in _TASK_STATUSES:
        return JsonResponse({"message": _("Invalid task status.")}, status=400)
    if request.POST.get("single_view"):
        candidate_task = CandidateTask.objects.select_for_update().filter(id=taskId).first()
    else:
        canId = request.POST.get("candId")
        candidate_task = CandidateTask.objects.filter(
            candidate_id_id=canId, onboarding_task_id_id=taskId
        ).select_for_update().first()
    if candidate_task is None:
        return JsonResponse({"message": _("Candidate task not found.")}, status=404)
    if not _can_manage_task(
        request, candidate_task.onboarding_task_id, "onboarding.change_candidatetask"
    ):
        return JsonResponse({"message": _("You don't have permission.")}, status=403)
    candidate_task.status = status
    candidate_task.save(update_fields=["status"])
    users = [
        employee.employee_user_id
        for employee in candidate_task.onboarding_task_id.employee_id.all()
    ]
    _notify_after_commit(
        request.user.employee_get,
        recipient=users,
        verb=f"The task {candidate_task.onboarding_task_id} of\
            {candidate_task.candidate_id} was updated to {candidate_task.status}.",
        verb_ar=f"تم تحديث المهمة {candidate_task.onboarding_task_id} للمرشح {candidate_task.candidate_id} إلى {candidate_task.status}.",
        verb_de=f"Die Aufgabe {candidate_task.onboarding_task_id} des Kandidaten {candidate_task.candidate_id} wurde auf {candidate_task.status} aktualisiert.",
        verb_es=f"La tarea {candidate_task.onboarding_task_id} del candidato {candidate_task.candidate_id} se ha actualizado a {candidate_task.status}.",
        verb_fr=f"La tâche {candidate_task.onboarding_task_id} du candidat {candidate_task.candidate_id} a été mise à jour à {candidate_task.status}.",
        icon="people-circle",
        redirect=reverse("onboarding-view"),
    )
    return JsonResponse(
        {"message": _("Candidate onboarding task updated"), "type": "success"}
    )


@login_required
def get_status(request, task_id):
    """
    htmx function that return the status of candidate task

    Parameters:
    request (HttpRequest): The HTTP request object.
    task_id : Onboarding task id

    Returns:
    POST : return candidate task template
    """
    cand_id = request.GET.get("cand_id")
    cand_stage = request.GET.get("cand_stage")
    if not cand_id or not cand_stage:
        return HorillaRedirect(request, message=_("Missing required parameters."))
    cand_stage_obj = CandidateStage.find(cand_stage)
    onboarding_task = OnboardingTask.find(task_id)
    candidate = Candidate.find(cand_id)
    candidate_task = CandidateTask.objects.filter(
        candidate_id=candidate, onboarding_task_id=onboarding_task
    ).first()
    if not cand_stage_obj or not onboarding_task or not candidate or not candidate_task:
        return HorillaRedirect(request, message=_("Object not found."))
    status = candidate_task.status

    return render(
        request,
        "onboarding/candidate_task.html",
        {
            "status": status,
            "task": onboarding_task,
            "candidate": cand_stage_obj,
            "second_load": True,
            "choices": CandidateTask.choice,
        },
    )


@login_required
@all_manager_can_enter("onboarding.change_candidatetask")
@require_POST
@transaction.atomic
def assign_task(request, task_id):
    """
    htmx function that used to assign a onboarding task to candidate

    Parameters:
    request (HttpRequest): The HTTP request object.
    task_id : Onboarding task id

    Returns:
    POST : return candidate task template
    """
    stage_id = request.POST.get("stage_id")
    cand_id = request.POST.get("cand_id")
    cand_stage = request.POST.get("cand_stage")
    if not stage_id or not cand_id or not cand_stage:
        return HorillaRedirect(request, message=_("Missing required parameters."))
    cand_stage_obj = CandidateStage.objects.select_for_update().filter(pk=cand_stage).first()
    onboarding_task = OnboardingTask.objects.filter(pk=task_id).first()
    candidate = Candidate.objects.filter(pk=cand_id).first()
    onboarding_stage = OnboardingStage.objects.filter(pk=stage_id).first()
    if (
        not cand_stage_obj
        or not onboarding_task
        or not candidate
        or not onboarding_stage
    ):
        return HorillaRedirect(request, message=_("Object not found."))

    if (
        cand_stage_obj.candidate_id_id != candidate.pk
        or cand_stage_obj.onboarding_stage_id_id != onboarding_stage.pk
        or onboarding_stage.recruitment_id_id != candidate.recruitment_id_id
        or onboarding_task.stage_id_id != onboarding_stage.pk
    ):
        return JsonResponse({"message": _("Task assignment scope is invalid.")}, status=400)
    if not _can_manage_task(
        request, onboarding_task, "onboarding.change_candidatetask"
    ):
        return JsonResponse({"message": _("You don't have permission.")}, status=403)

    cand_task, _created = CandidateTask.objects.get_or_create(
        candidate_id=candidate,
        stage_id=onboarding_stage,
        onboarding_task_id=onboarding_task,
    )
    onboarding_task.candidates.add(candidate)
    return render(
        request,
        "onboarding/candidate_task.html",
        {
            "status": cand_task.status,
            "task": onboarding_task,
            "candidate": cand_stage_obj,
            "second_load": True,
            "choices": CandidateTask.choice,
        },
    )


@login_required
@require_http_methods(["POST"])
@stage_manager_can_enter("onboarding.change_candidatestage")
@transaction.atomic
def candidate_stage_update(request, candidate_id, recruitment_id):
    """
    function used to update candidate stage.

    Parameters:
    request (HttpRequest): The HTTP request object.
    candidate_id : Candidate id
    recruitment_id : Recruitment id

    Returns:
    POST : return candidate task template
    """
    stage_id = request.POST.get("stage")
    recruitment = Recruitment.objects.filter(id=recruitment_id).first()
    if recruitment is None:
        return JsonResponse({"message": _("Recruitment not found.")}, status=404)
    stage = OnboardingStage.objects.filter(
        id=stage_id, recruitment_id=recruitment
    ).first()
    candidate = Candidate.objects.filter(
        id=candidate_id, recruitment_id=recruitment
    ).first()
    if stage is None or candidate is None:
        return JsonResponse({"message": _("Candidate or stage not found.")}, status=404)
    if not _can_manage_stage(
        request, stage, "onboarding.change_candidatestage"
    ):
        return JsonResponse({"message": _("You don't have permission.")}, status=403)
    candidate_stage = CandidateStage.objects.select_for_update().filter(
        candidate_id=candidate
    ).first()
    if candidate_stage is None:
        return JsonResponse({"message": _("Candidate stage not found.")}, status=404)
    candidate_stage.onboarding_stage_id = stage
    candidate_stage.save()
    onboarding_stages = OnboardingStage.objects.all()
    choices = CandidateTask.choice
    users = [
        employee.employee_user_id
        for employee in candidate_stage.onboarding_stage_id.employee_id.all()
    ]
    if request.POST.get("is_ajax") is None:
        _notify_after_commit(
            request.user.employee_get,
            recipient=users,
            verb=f"The stage of {candidate_stage.candidate_id} \
                was updated to {candidate_stage.onboarding_stage_id}.",
            verb_ar=f"تم تحديث مرحلة المرشح {candidate_stage.candidate_id} إلى {candidate_stage.onboarding_stage_id}.",
            verb_de=f"Die Phase des Kandidaten {candidate_stage.candidate_id} wurde auf {candidate_stage.onboarding_stage_id} aktualisiert.",
            verb_es=f"La etapa del candidato {candidate_stage.candidate_id} se ha actualizado a {candidate_stage.onboarding_stage_id}.",
            verb_fr=f"L'étape du candidat {candidate_stage.candidate_id} a été mise à jour à {candidate_stage.onboarding_stage_id}.",
            icon="people-circle",
            redirect=reverse("onboarding-view"),
        )
    groups = onboarding_query_grouper(request, Recruitment.objects.filter(pk=recruitment.pk))
    for item in groups:
        setattr(item["recruitment"], "stages", item["stages"])
        return render(
            request,
            "onboarding/onboarding_table.html",
            {
                "recruitment": groups[0]["recruitment"],
                "onboarding_stages": onboarding_stages,
                "choices": choices,
            },
        )
    return JsonResponse(
        {"message": _("Candidate onboarding stage updated"), "type": "success"}
    )


@login_required
@require_http_methods(["POST"])
@stage_manager_can_enter("onboarding.change_candidatestage")
@transaction.atomic
def candidate_stage_bulk_update(request):
    try:
        candidate_id_list = _parse_json_id_list(request.POST.get("ids"))
        recruitment_id = int(request.POST.get("recruitment", ""))
        stage_id = int(request.POST.get("stage", ""))
    except (TypeError, ValueError):
        return JsonResponse({"message": _("Invalid bulk update request.")}, status=400)
    recruitment = Recruitment.objects.filter(pk=recruitment_id).first()
    stage = OnboardingStage.objects.filter(
        pk=stage_id, recruitment_id=recruitment
    ).first()
    candidates = Candidate.objects.filter(
        pk__in=candidate_id_list, recruitment_id=recruitment
    )
    if recruitment is None or stage is None or candidates.count() != len(candidate_id_list):
        return JsonResponse({"message": _("Candidate or stage not found.")}, status=404)
    if not _can_manage_stage(
        request, stage, "onboarding.change_candidatestage"
    ):
        return JsonResponse({"message": _("You don't have permission.")}, status=403)
    onboarding_stages = OnboardingStage.objects.all()
    recruitments = Recruitment.objects.filter(id=recruitment_id)

    choices = CandidateTask.choice

    candidate_stages = CandidateStage.objects.select_for_update().filter(
        candidate_id__id__in=candidate_id_list,
        candidate_id__recruitment_id=recruitment,
    )
    if candidate_stages.count() != len(candidate_id_list):
        return JsonResponse({"message": _("Candidate stage not found.")}, status=404)
    candidate_stages.update(onboarding_stage_id=stage)
    type = "info"
    message = "No candidates selected"
    if candidate_id_list:
        type = "success"
        message = "Candidate stage updated successfully"
    groups = onboarding_query_grouper(request, recruitments)
    for item in groups:
        setattr(item["recruitment"], "stages", item["stages"])
    response = render(
        request,
        "onboarding/onboarding_table.html",
        {
            "recruitment": groups[0]["recruitment"],
            "onboarding_stages": onboarding_stages,
            "choices": choices,
        },
    )

    return HttpResponse(
        response.content.decode("utf-8")
        + f'<div><div class="oh-alert-container"><div class="oh-alert oh-alert--animated oh-alert--{type}">{message}</div> </div></div>'
    )


@login_required
@require_http_methods(["POST"])
@all_manager_can_enter("onboarding.change_candidatetask")
@transaction.atomic
def candidate_task_bulk_update(request):
    try:
        candidate_id_list = _parse_json_id_list(request.POST.get("ids"))
        task_id = int(request.POST.get("task", ""))
    except (TypeError, ValueError):
        return JsonResponse({"message": _("Invalid bulk update request.")}, status=400)
    status = request.POST.get("status", "")
    if status not in _TASK_STATUSES:
        return JsonResponse({"message": _("Invalid task status.")}, status=400)
    task = OnboardingTask.objects.filter(pk=task_id).first()
    if task is None:
        return JsonResponse({"message": _("Task not found.")}, status=404)
    if not _can_manage_task(
        request, task, "onboarding.change_candidatetask"
    ):
        return JsonResponse({"message": _("You don't have permission.")}, status=403)
    eligible_ids = set(
        task.candidates.filter(pk__in=candidate_id_list).values_list("pk", flat=True)
    )
    if len(eligible_ids) != len(candidate_id_list):
        return JsonResponse({"message": _("Candidate is not assigned to this task.")}, status=404)

    candidate_tasks = CandidateTask.objects.select_for_update().filter(
        candidate_id__id__in=candidate_id_list, onboarding_task_id=task
    )
    if candidate_tasks.count() != len(candidate_id_list):
        return JsonResponse({"message": _("Candidate task not found.")}, status=404)
    count = candidate_tasks.update(status=status)
    # messages.success(request, _("%(count)s candidate's task status updated successfully") % {"count": count})

    return JsonResponse(
        {"message": _("Candidate onboarding stage updated"), "type": "success"}
    )


@login_required
def onboard_candidate_chart(request):
    """
    function used to show onboard started candidates in recruitments.

    Parameters:
    request (HttpRequest): The HTTP request object.

    Returns:
    GET : return Json response labels, data, background_color, border_color.
    """
    labels = []
    data = []
    background_color = []
    border_color = []
    recruitments = Recruitment.objects.filter(closed=False, is_active=True)
    for recruitment in recruitments:
        red = random.randint(0, 255)
        green = random.randint(0, 255)
        blue = random.randint(0, 255)
        background_color.append(f"rgba({red}, {green}, {blue}, 0.2")
        border_color.append(f"rgb({red}, {green}, {blue})")
        labels.append(recruitment.title)
        data.append(recruitment.candidate.filter(start_onboard=True).count())
    return JsonResponse(
        {
            "labels": labels,
            "data": data,
            "background_color": background_color,
            "border_color": border_color,
            "message": _("No records available at the moment."),
        },
        safe=False,
    )


@login_required
@permission_required("recruitment.change_candidate")
@require_POST
@transaction.atomic
def update_joining(request):
    """
    Ajax method to update joining date of candidate
    """
    cand_id = request.POST.get("candId")
    date_value = request.POST.get("date")

    if not cand_id:
        messages.error(request, _("Missing candidate ID."))
        return JsonResponse({"type": "danger"}, status=400)

    if date_value is None:
        messages.error(request, _("Missing date of joining."))
        return JsonResponse({"type": "danger"}, status=400)

    try:
        date_value = date.fromisoformat(date_value) if date_value else None
    except ValueError:
        messages.error(request, _("Invalid date of joining."))
        return JsonResponse({"type": "danger"}, status=400)

    candidate_obj = Candidate.objects.select_for_update().filter(
        id=cand_id, onboarding_stage__isnull=False
    ).first()
    if not candidate_obj:
        messages.error(request, _("Candidate not found"))
        return JsonResponse({"type": "danger"}, status=400)

    candidate_obj.joining_date = date_value
    candidate_obj.save(update_fields=["joining_date"])
    messages.success(
        request,
        _("{candidate}'s Date of joining updated successfully").format(
            candidate=candidate_obj.name
        ),
    )
    return JsonResponse({"type": "success"})


@login_required
@permission_required(perm="recruitment.view_candidate")
def view_dashboard(request):
    recruitment = Recruitment.objects.all().values_list("title", flat=True)
    candidates = Candidate.objects.all()
    hired = candidates.filter(start_onboard=True)
    onboard_candidates = Candidate.objects.filter(start_onboard=True)
    job_positions = onboard_candidates.values_list(
        "job_position_id__job_position", flat=True
    )

    context = {
        "recruitment": list(recruitment),
        "candidates": candidates,
        "hired": hired,
        "onboard_candidates": onboard_candidates,
        "job_positions": list(set(job_positions)),
    }
    return render(request, "onboarding/dashboard.html", context=context)


@login_required
@hx_request_required
@permission_required(perm="recruitment.view_candidate")
def dashboard_stage_chart(request):
    recruitment = request.GET.get("recruitment")
    labels = OnboardingStage.objects.filter(
        recruitment_id__title=recruitment
    ).values_list("stage_title", flat=True)
    labels = list(labels)
    candidate_counts = []
    border_color = []
    background_color = []
    for label in labels:
        red = random.randint(0, 255)
        green = random.randint(0, 255)
        blue = random.randint(0, 255)
        background_color.append(f"rgba({red}, {green}, {blue}, 0.3")
        border_color.append(f"rgb({red}, {green}, {blue})")
        count = CandidateStage.objects.filter(
            onboarding_stage_id__stage_title=label,
            onboarding_stage_id__recruitment_id__title=recruitment,
        ).count()
        candidate_counts.append(count)

    response = {
        "labels": labels,
        "data": candidate_counts,
        "recruitment": recruitment,
        "background_color": background_color,
        "border_color": border_color,
        "message": _("No candidates started onboarding...."),
    }
    return JsonResponse(response)


@login_required
@stage_manager_can_enter("recruitment.change_candidate")
@require_POST
@transaction.atomic
def candidate_sequence_update(request):
    """
    This method is used to update the sequence of candidate
    """
    try:
        sequence_data = _parse_sequence_map(request.POST.get("sequenceData"))
    except ValueError:
        return JsonResponse({"error": _("Invalid sequence data.")}, status=400)
    candidate_stages = list(
        CandidateStage.objects.select_for_update()
        .select_related("onboarding_stage_id__recruitment_id")
        .filter(id__in=sequence_data)
    )
    if len(candidate_stages) != len(sequence_data):
        return JsonResponse({"error": _("Candidate stage not found.")}, status=404)
    stage_ids = {item.onboarding_stage_id_id for item in candidate_stages}
    if len(stage_ids) != 1:
        return JsonResponse(
            {"error": _("Candidates must belong to one onboarding stage.")}, status=400
        )
    stage = candidate_stages[0].onboarding_stage_id
    if not _can_manage_stage(request, stage, "recruitment.change_candidate"):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)
    for candidate_stage in candidate_stages:
        candidate_stage.sequence = sequence_data[candidate_stage.pk]
    CandidateStage.objects.bulk_update(candidate_stages, ["sequence"])
    return JsonResponse(
        {"message": _("Candidate sequence updated"), "type": "info"}
    )


@login_required
@stage_manager_can_enter("recruitment.change_stage")
@require_POST
@transaction.atomic
def stage_sequence_update(request):
    """
    This method is used to update the sequence of the stages
    """
    try:
        sequence_data = _parse_sequence_map(request.POST.get("sequenceData"))
    except ValueError:
        return JsonResponse({"error": _("Invalid sequence data.")}, status=400)
    stages = list(
        OnboardingStage.objects.select_for_update()
        .select_related("recruitment_id")
        .filter(id__in=sequence_data)
    )
    if len(stages) != len(sequence_data):
        return JsonResponse({"error": _("Stage not found.")}, status=404)
    recruitment_ids = {stage.recruitment_id_id for stage in stages}
    if len(recruitment_ids) != 1:
        return JsonResponse(
            {"error": _("Stages must belong to one recruitment.")}, status=400
        )
    recruitment = stages[0].recruitment_id
    if not _can_manage_recruitment(
        request, recruitment, "recruitment.change_stage"
    ):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)
    for stage in stages:
        stage.sequence = sequence_data[stage.pk]
    OnboardingStage.objects.bulk_update(stages, ["sequence"])
    return JsonResponse({"type": "success", "message": _("Stage sequence updated")})


@login_required
@require_http_methods(["POST"])
@hx_request_required
@stage_manager_can_enter("onboarding.change_onboardingstage")
@transaction.atomic
def stage_name_update(request, stage_id):
    """
    This method is used to update the name of recruitment stage
    """
    stage_obj = (
        OnboardingStage.objects.select_for_update()
        .select_related("recruitment_id")
        .filter(id=stage_id)
        .first()
    )
    if stage_obj is None:
        return JsonResponse({"message": _("Stage not found.")}, status=404)
    if not _can_manage_stage(
        request, stage_obj, "onboarding.change_onboardingstage"
    ):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)
    title = request.POST.get("stage", "").strip()
    if not title or len(title) > 200:
        return JsonResponse({"message": _("Invalid stage title.")}, status=400)
    stage_obj.stage_title = title
    stage_obj.save(update_fields=["stage_title"])
    message = _("The stage title has been updated successfully")
    return HttpResponse(
        f'<div class="oh-alert-container"><div class="oh-alert oh-alert--animated oh-alert--success">{message}</div></div>'
    )


@login_required
@hx_request_required
@stage_manager_can_enter("recruitment.change_candidate")
def onboarding_send_mail(request, candidate_id):
    """
    This method is used to send mail to the candidate from onboarding view
    """
    candidate = Candidate.objects.get(id=candidate_id)
    candidate_mail = candidate.email
    response = render(
        request, "onboarding/send_mail_form.html", {"candidate": candidate}
    )
    email_backend = ConfiguredEmailBackend()
    display_email_name = email_backend.dynamic_from_email_with_display_name
    if request:
        try:
            display_email_name = f"{request.user.employee_get.get_full_name()} <{request.user.employee_get.email}>"
        except:
            logger.error(Exception)

    if request.method == "POST":
        subject = request.POST["subject"]
        body = request.POST["body"]
        with contextlib.suppress(Exception):
            res = send_mail(
                subject,
                body,
                display_email_name,
                [candidate_mail],
                fail_silently=False,
            )
            if res == 1:
                messages.success(request, _("Mail sent successfully"))
            else:
                messages.error(request, _("Something went wrong"))
        return HttpResponse(
            response.content.decode("utf-8") + "<script>location.reload();</script>"
        )

    return response


@login_required
@stage_manager_can_enter("recruitment.change_candidate")
@require_POST
@transaction.atomic
def update_probation_end(request):
    """
    Updates the probation end date for a candidate.
    """
    candidate_id = request.POST.get("candidate_id")
    probation_end = request.POST.get("probation_end")

    if not candidate_id:
        messages.error(request, _("Missing candidate ID."))
        return JsonResponse({"type": "danger"}, status=400)

    candidate_stage = (
        CandidateStage.objects.select_for_update()
        .select_related("onboarding_stage_id__recruitment_id", "candidate_id")
        .filter(candidate_id_id=candidate_id)
        .first()
    )
    if candidate_stage is None:
        messages.error(request, _("Candidate not found."))
        return JsonResponse({"type": "danger"}, status=404)
    if not _can_manage_stage(
        request, candidate_stage.onboarding_stage_id, "recruitment.change_candidate"
    ):
        return JsonResponse({"message": _("You do not have permission.")}, status=403)

    try:
        probation_end = date.fromisoformat(probation_end) if probation_end else None
    except ValueError:
        return JsonResponse({"message": _("Invalid probation end date.")}, status=400)

    candidate = Candidate.objects.select_for_update().get(pk=candidate_stage.candidate_id_id)
    candidate.probation_end = probation_end
    candidate.save(update_fields=["probation_end"])
    messages.success(request, _("Probation end date updated"))
    return JsonResponse({"type": "success"})


@login_required
@hx_request_required
@all_manager_can_enter("onboarding.change_onboardingtask")
def task_report(request):
    """
    This method is used to show the task report.
    """
    employee_id = request.GET.get("employee_id")
    if not employee_id:
        employee_id = request.user.employee_get.id
    my_tasks = OnboardingTask.objects.filter(
        employee_id__id=employee_id,
        candidates__is_active=True,
        candidates__recruitment_id__closed=False,
    ).distinct()
    tasks = []
    for task in my_tasks:
        tasks.append(
            {
                "task": task,
                "total_candidates": task.candidatetask_set.count(),
                "todo": task.candidatetask_set.filter(status="todo").count(),
                "scheduled": task.candidatetask_set.filter(status="scheduled").count(),
                "ongoing": task.candidatetask_set.filter(status="ongoing").count(),
                "stuck": task.candidatetask_set.filter(status="stuck").count(),
                "done": task.candidatetask_set.filter(status="done").count(),
            }
        )
    return render(request, "onboarding/dashboard/task_report.html", {"tasks": tasks})


@login_required
@all_manager_can_enter("onboarding.view_candidatetask")
def candidate_tasks_status(request):
    """
    This method is used to render template to show the onboarding tasks
    """
    task_id = request.GET["task_id"]
    candidate_tasks = CandidateTask.objects.filter(onboarding_task_id__id=task_id)
    return render(
        request,
        "onboarding/dashboard/status_list.html",
        {"candidate_tasks": candidate_tasks},
    )


@login_required
@all_manager_can_enter("onboarding.change_candidatetask")
@require_POST
@transaction.atomic
def change_task_status(request):
    """
    This method is to update the candidate task
    """
    task_id = request.POST.get("task_id")
    status = request.POST.get("status")
    if not task_id or not status:
        return HorillaRedirect(request, message=_("Task ID or status is missing"))
    candidate_task = CandidateTask.objects.select_for_update().filter(pk=task_id).first()
    if not candidate_task:
        return HorillaRedirect(request, message=_("Candidate task not found"))
    if status not in _TASK_STATUSES:
        return JsonResponse({"message": _("Invalid task status.")}, status=400)
    if not _can_manage_task(
        request, candidate_task.onboarding_task_id, "onboarding.change_candidatetask"
    ):
        return JsonResponse({"message": _("You don't have permission.")}, status=403)
    candidate_task.status = status
    candidate_task.save(update_fields=["status"])
    messages.success(request, _("Task status updated successfully."))

    return HttpResponse(
        "<script>$('#reloadMessagesButton').click(); $('#myOnboardingReload').click(); </script>"
    )


@login_required
@permission_required("recruitment.change_candidate")
@require_POST
@transaction.atomic
def update_offer_letter_status(request):
    """
    This method is used to update the offer letter status
    """
    candidate_id = request.POST.get("candidate_id")
    status = request.POST.get("status")
    if not candidate_id or not status:
        messages.error(request, _("candidate or status is missing"))
        return redirect("/onboarding/candidates-view/")
    if status not in _OFFER_STATUSES:
        messages.error(request, _("Please Pass valid status"))
        return redirect("/onboarding/candidates-view/")
    try:
        candidate = Candidate.objects.select_for_update().get(id=candidate_id)
    except Candidate.DoesNotExist:
        messages.error(request, _("Candidate not found"))
        return redirect("/onboarding/candidates-view/")
    candidate.offer_letter_status = status
    candidate.save(update_fields=["offer_letter_status"])
    messages.success(request, _("Status of offer letter updated successfully"))
    url = "/onboarding/candidates-view/"
    return HttpResponse(
        f"""
                <script>
                window.location.href="{url}"
                </script>
                """
    )


@login_required
@hx_request_required
@permission_required("recruitment.add_rejectedcandidate")
@transaction.atomic
def add_to_rejected_candidates(request):
    """
    This method is used to add candidates to rejected candidates
    """
    candidate_id = (
        request.POST.get("candidate_id")
        if request.method == "POST"
        else request.GET.get("candidate_id")
    )
    instance = None
    if candidate_id:
        candidate = Candidate.objects.filter(pk=candidate_id).first()
        if candidate is None:
            return HorillaRedirect(request, message=_("Candidate not found."))
        instance = RejectedCandidate.objects.select_for_update().filter(
            candidate_id=candidate
        ).first()
    form = RejectedCandidateForm(
        initial={"candidate_id": candidate_id}, instance=instance
    )
    if request.method == "POST":
        form = RejectedCandidateForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            form = RejectedCandidateForm()
            messages.success(request, _("Candidate reject reason saved"))
            return HorillaRedirect(request)
    return render(request, "onboarding/rejection/form.html", {"form": form})


@login_required
@permission_required("recruitment.change_candidate")
@require_http_methods(["POST"])
@transaction.atomic
def undo_rejected_candidate(request, candidate_id):
    """
    Remove candidate from rejected list.
    """
    rejected = RejectedCandidate.objects.select_for_update().filter(
        candidate_id=candidate_id
    )
    deleted_count, __ = rejected.delete()
    if deleted_count:
        messages.success(request, _("Candidate removed from rejected list"))
    else:
        messages.info(request, _("Candidate is not in rejected list"))

    if request.META.get("HTTP_HX_REQUEST") == "true":
        response = HttpResponse(
            "<script>"
            "$('#applyFilter').click();"
            "$('#reloadMessagesButton').click();"
            "</script>"
        )
        # Also trigger via HX-Trigger header so listeners (#applyFilter / #reloadMessagesButton)
        # fire even when the button uses hx-swap="none" (which discards the response body).
        response["HX-Trigger"] = "reloadCandidatesList"
        return response
    return HorillaRedirect(request)


@login_required
@hx_request_required
def candidate_select(request):
    """
    This method is used for select all in candidate
    """
    page_number = request.GET.get("page")

    employees = queryset = Candidate.objects.filter(
        hired=True,
        recruitment_id__closed=False,
        is_active=True,
    )

    employee_ids = [str(emp.id) for emp in employees]
    total_count = employees.count()

    context = {"employee_ids": employee_ids, "total_count": total_count}

    return JsonResponse(context, safe=False)


@login_required
@permission_required("recruitment.view_candidate")
def candidate_select_filter(request):
    """
    This method is used to select all filtered candidates
    """
    page_number = request.GET.get("page")
    filtered = request.GET.get("filter")
    filters = json.loads(filtered) if filtered else {}

    if page_number == "all":
        candidate_filter = CandidateFilter(
            filters,
            queryset=Candidate.objects.filter(
                hired=True,
                recruitment_id__closed=False,
                is_active=True,
            ),
        )

        # Get the filtered queryset
        filtered_candidates = candidate_filter.qs

        employee_ids = [str(emp.id) for emp in filtered_candidates]
        total_count = filtered_candidates.count()

        context = {"employee_ids": employee_ids, "total_count": total_count}

        return JsonResponse(context)
    else:
        messages.error(request, _("Invalid page number"))
        return JsonResponse(
            {"message": _("Invalid page number")}, status=400, safe=False
        )


@login_required
@permission_required("recruitment.change_candidate")
@require_POST
@transaction.atomic
def offer_letter_bulk_status_update(request):
    """
    This function is used to bulk update the offerletter status
    """
    letter_ids = request.POST.get("ids")

    if not letter_ids:
        messages.error(request, _("No offer letters selected for status update."))
        return JsonResponse("Missing required parameter: ids", safe=False, status=400)

    try:
        ids = _parse_json_id_list(letter_ids)
    except ValueError:
        return JsonResponse({"message": _("Invalid candidate list.")}, status=400)
    status = request.POST.get("status", "")
    if status not in _OFFER_STATUSES:
        return JsonResponse({"message": _("Invalid offer status.")}, status=400)
    candidates = Candidate.objects.select_for_update().filter(id__in=ids)
    if candidates.count() != len(ids):
        return JsonResponse({"message": _("Candidate not found.")}, status=404)
    updated = candidates.exclude(offer_letter_status=status).update(
        offer_letter_status=status
    )
    messages.success(
        request,
        _("Offer letter status updated for %(count)s candidates.")
        % {"count": updated},
    )
    return JsonResponse({"status": "success", "updated": updated})


@login_required
@permission_required("recruitment.delete_candidate")
@require_POST
@transaction.atomic
def onboarding_candidate_bulk_delete(request):
    """
    This function is used to bulk delete onboarding candidates
    """

    cand_ids = request.POST.get("ids")
    if not cand_ids:
        messages.error(request, _("No candidates selected for deletion."))
        return JsonResponse("Missing required parameter: ids", safe=False, status=400)

    try:
        ids = _parse_json_id_list(cand_ids)
    except ValueError:
        return JsonResponse({"message": _("Invalid candidate list.")}, status=400)
    candidates = list(Candidate.objects.select_for_update().filter(id__in=ids))
    if len(candidates) != len(ids):
        return JsonResponse({"message": _("Candidate not found.")}, status=404)
    try:
        for candidate in candidates:
            candidate.delete()
    except ProtectedError:
        transaction.set_rollback(True)
        transaction.set_rollback(True)
        transaction.set_rollback(True)
        return JsonResponse(
            {"message": _("A selected candidate is referenced by protected records.")},
            status=409,
        )
    messages.success(request, _("Candidates deleted successfully."))
    return JsonResponse({"status": "success", "deleted": len(candidates)})
