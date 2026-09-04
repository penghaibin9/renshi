"""
actions.py

This module is used to register methods to delete/archive/un-archive instances
"""

import contextlib
import json

from django import template
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as __
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from base.forms import MailTemplateForm
from base.methods import (
    build_safe_template_request,
    sanitize_mail_template_body,
    sanitize_mail_template_placeholders,
)
from base.models import HorillaMailTemplate
from employee.models import Employee
from horilla.decorators import hx_request_required, login_required, permission_required
from horilla.group_by import group_by_queryset
from horilla.http import HorillaRedirect
from notifications.signals import notify
from recruitment.decorators import (
    candidate_login_required,
    manager_can_enter,
    recruitment_manager_can_enter,
)
from recruitment.filters import StageFilter
from recruitment.forms import StageCreationForm
from recruitment.models import Candidate, Recruitment, Stage, StageNote
from recruitment.views.linkedin import delete_post
from recruitment.views.paginator_qry import paginator_qry
from recruitment.views.views import (
    _can_manage_recruitment,
    _parse_posted_ids,
    _permission_denied_json,
)


def _notify_safely(sender, **kwargs):
    with contextlib.suppress(Exception):
        notify.send(sender, **kwargs)


@login_required
@permission_required(perm="recruitment.delete_recruitment")
@require_http_methods(["POST"])
@transaction.atomic
def recruitment_delete(request, rec_id):
    """
    This method is used to permanently delete the recruitment
    Args:
        id : recruitment_id
    """
    try:
        try:
            recruitment_obj = (
                Recruitment.objects.select_for_update()
                .select_related("linkedin_account_id")
                .get(id=rec_id)
            )
        except Recruitment.DoesNotExist:
            messages.error(request, _("Recruitment not found."))
            return HorillaRedirect(request)
        recruitment_mangers = recruitment_obj.recruitment_managers.all()
        all_stage_permissions = Permission.objects.filter(
            content_type__app_label="recruitment", content_type__model="stage"
        )
        all_candidate_permissions = Permission.objects.filter(
            content_type__app_label="recruitment", content_type__model="candidate"
        )
        for manager in recruitment_mangers:
            all_this_manger = manager.recruitment_set.all()
            if len(all_this_manger) == 1:
                for stage_permission in all_candidate_permissions:
                    manager.employee_user_id.user_permissions.remove(
                        stage_permission.id
                    )
                for candidate_permission in all_stage_permissions:
                    manager.employee_user_id.user_permissions.remove(
                        candidate_permission.id
                    )
        try:
            recruitment_obj.delete()
            transaction.on_commit(
                lambda: delete_post(recruitment_obj, persist=False)
            )
            messages.success(request, _("Recruitment deleted successfully."))

        except ProtectedError as e:
            transaction.set_rollback(True)
            model_verbose_name_sets = set()
            for obj in e.protected_objects:
                model_verbose_name_sets.add(__(obj._meta.verbose_name.capitalize()))
            model_verbose_name_str = (",").join(model_verbose_name_sets)
            messages.error(
                request,
                _(
                    "You cannot delete this recruitment as it is using in {}".format(
                        model_verbose_name_str
                    )
                ),
            )
        recruitment_obj = Recruitment.objects.all()
    except (Recruitment.DoesNotExist, OverflowError):
        messages.error(request, _("Recruitment Does not exists.."))
    if request.META.get("HTTP_HX_REQUEST") == "true":
        return HttpResponse(
            "<script>"
            "$('#applyFilter').click();"
            "$('#reloadMessagesButton').click();"
            "</script>"
        )
    return HorillaRedirect(request)


@login_required
@permission_required(perm="recruitment.delete_recruitment")
@require_http_methods(["POST"])
@transaction.atomic
def recruitment_delete_pipeline(request, rec_id):
    """This method is used to delete the recruitment instance

    Args:
        id: recruitment instance id
    Returns:
        HorillaRedirect: Used to refresh the page
    """
    try:
        recruitment_obj = Recruitment.objects.select_for_update().get(id=rec_id)
        recruitment_obj.delete()
        messages.success(request, _("Recruitment deleted."))
    except Recruitment.DoesNotExist:
        messages.error(request, _("Recruitment not found."))
    except ProtectedError as e:
        transaction.set_rollback(True)
        models_verbose_name_sets = set()
        for obj in e.protected_objects:
            models_verbose_name_sets.add(__(obj._meta.verbose_name.capitalize()))
        models_verbose_name_str = (",").join(models_verbose_name_sets)
        messages.error(
            request,
            _("Recruitment already in use for {}.".format(models_verbose_name_str)),
        )
    return HorillaRedirect(request)


@login_required
@manager_can_enter(perm="recruitment.delete_stagenote")
@require_http_methods(["POST"])
@transaction.atomic
def note_delete(request, note_id):
    """
    This method is used to delete the stage note
    """
    try:
        note = (
            StageNote.objects.select_for_update()
            .select_related("candidate_id__recruitment_id")
            .get(id=note_id)
        )
        if not _can_manage_recruitment(
            request,
            note.candidate_id.recruitment_id,
            "recruitment.delete_stagenote",
            include_stage_managers=True,
        ):
            return _permission_denied_json()
        candidate_id = note.candidate_id.id
        note.delete()
        messages.success(request, _("Note deleted"))
        script = ""
    except StageNote.DoesNotExist:
        return HorillaRedirect(request, message=_("Note not found."))
    except ProtectedError:
        transaction.set_rollback(True)
        messages.error(request, _("You cannot delete this note."))
        script = f"""
            <span hx-trigger='load' hx-get='/recruitment/view-note/{candidate_id}/' hx-target='#activitySidebar'></span>
            """
    return HttpResponse(script)


@candidate_login_required
@hx_request_required
@require_http_methods(["POST"])
@transaction.atomic
# @manager_can_enter(perm="recruitment.delete_stagenote")
def note_delete_individual(request, note_id):
    """
    This method is used to delete the stage note
    """
    note = (
        StageNote.objects.select_for_update()
        .select_related("candidate_id__recruitment_id")
        .filter(id=note_id)
        .first()
    )
    session_candidate_id = request.session.get("candidate_id")
    if note is None:
        return JsonResponse({"message": _("Note not found.")}, status=404)
    if session_candidate_id and str(note.candidate_id_id) != str(session_candidate_id):
        return JsonResponse({"message": _("Note not found.")}, status=404)
    if not session_candidate_id and not _can_manage_recruitment(
        request,
        note.candidate_id.recruitment_id,
        "recruitment.delete_stagenote",
        include_stage_managers=True,
    ):
        return _permission_denied_json()
    note.delete()
    messages.success(request, _("Note deleted."))
    return HttpResponse("")


@login_required
@manager_can_enter(perm="recruitment.delete_stage")
@require_http_methods(["POST", "DELETE"])
@transaction.atomic
def stage_delete(request, stage_id):
    """
    This method is used to delete stage permanently
    Args:
        id : stage_id
    """
    try:
        try:
            stage_obj = (
                Stage.objects.select_for_update()
                .select_related("recruitment_id")
                .get(id=stage_id)
            )
            if not _can_manage_recruitment(
                request,
                stage_obj.recruitment_id,
                "recruitment.delete_stage",
                include_stage_managers=True,
            ):
                return _permission_denied_json()
            recruitment_id = stage_obj.recruitment_id.id
        except Stage.DoesNotExist:
            messages.error(request, _("Stage not found."))
            return HorillaRedirect(request)

        stage_managers = stage_obj.stage_managers.all()
        for manager in stage_managers:
            all_this_manger = manager.stage_set.all()
            if len(all_this_manger) == 1:
                view_recruitment = Permission.objects.get(codename="view_recruitment")
                manager.employee_user_id.user_permissions.remove(view_recruitment.id)
            initial_stage_manager = all_this_manger.filter(stage_type="initial")
            if len(initial_stage_manager) == 1:
                add_candidate = Permission.objects.get(
                    codename="recruitment.add_candidate"
                )
                change_candidate = Permission.objects.get(codename="change_candidate")
                manager.employee_user_id.user_permissions.remove(add_candidate.id)
                manager.employee_user_id.user_permissions.remove(change_candidate.id)
            stage_obj.stage_managers.remove(manager)
        try:
            stage_obj.delete()
            messages.success(request, _("Stage deleted successfully."))
        except ProtectedError as e:
            transaction.set_rollback(True)
            models_verbose_name_sets = set()
            for obj in e.protected_objects:
                models_verbose_name_sets.add(__(obj._meta.verbose_name.capitalize()))
            models_verbose_name_str = (",").join(models_verbose_name_sets)
            messages.error(
                request,
                _(
                    "You cannot delete this stage while it's in use for {}".format(
                        models_verbose_name_str
                    )
                ),
            )
    except (Stage.DoesNotExist, OverflowError):
        messages.error(request, _("Stage Does not exists.."))
    hx_request = request.META.get("HTTP_HX_REQUEST")
    hx_current_url = request.META.get("HTTP_HX_CURRENT_URL")
    if hx_request and hx_request == "true":
        if hx_current_url and "stage-view" in hx_current_url:
            return HttpResponse(
                "<script>"
                "$('#applyFilter').click();"
                "$('#reloadMessagesButton').click();"
                "</script>"
            )
        return HttpResponse(
            "<script>" "$('#reloadMessagesButton').click();" "</script>"
        )
    return HorillaRedirect(request)


@login_required
@permission_required(perm="recruitment.delete_candidate")
@require_http_methods(["DELETE", "POST"])
@transaction.atomic
def candidate_delete(request, cand_id):
    """
    This method is used to delete candidate permanently
    Args:
        id : candidate_id
    """
    try:
        try:
            Candidate.objects.select_for_update().get(id=cand_id).delete()
            messages.success(request, _("Candidate deleted successfully."))
        except Candidate.DoesNotExist:
            messages.error(request, _("Candidate not found."))
        except ProtectedError as e:
            transaction.set_rollback(True)
            models_verbose_name_set = set()
            for obj in e.protected_objects:
                models_verbose_name_set.add(__(obj._meta.verbose_name.capitalize()))
            models_verbose_name_str = (",").join(models_verbose_name_set)
            messages.error(
                request,
                _(
                    "You cannot delete this candidate because the candidate is in {}.".format(
                        models_verbose_name_str
                    )
                ),
            )
    except (Candidate.DoesNotExist, OverflowError):
        messages.error(request, _("Candidate Does not exists."))
    if request.META.get("HTTP_HX_REQUEST") == "true":
        response = HttpResponse(status=204)
        response["HX-Trigger"] = "candidateContainerReload"
        return response
    return HorillaRedirect(request)


@login_required
@permission_required(perm="recruitment.delete_candidate")
@require_http_methods(["POST"])
@transaction.atomic
def candidate_bulk_delete(request):
    """
    This method is used to bulk delete candidates
    """
    try:
        ids = _parse_posted_ids(request.POST.get("ids"))
    except ValueError:
        return JsonResponse({"message": _("Invalid candidate selection.")}, status=400)
    candidates = Candidate.objects.select_for_update().filter(id__in=ids)
    if candidates.count() != len(ids):
        return JsonResponse({"message": _("Candidate not found.")}, status=404)
    try:
        candidates.delete()
    except ProtectedError:
        transaction.set_rollback(True)
        return JsonResponse(
            {"message": _("One or more selected candidates are in use.")}, status=409
        )
    messages.success(request, _("Selected candidates deleted successfully."))
    return JsonResponse({"message": "Success", "deleted": len(ids)})


@login_required
@permission_required(perm="recruitment.delete_candidate")
@require_http_methods(["POST"])
@transaction.atomic
def candidate_archive(request, cand_id):
    """
    This method is used to archive or un-archive candidates
    """
    try:
        candidate_obj = Candidate.objects.select_for_update().get(id=cand_id)
        new_state = not candidate_obj.is_active
        # Use queryset .update() to bypass Candidate.save() validation
        # (job_position_id checks against recruitment.open_positions), since
        # archiving should only toggle is_active and not re-validate the
        # candidate's recruitment data.
        Candidate.objects.filter(id=cand_id).update(is_active=new_state)
        message = _("archived") if not new_state else _("un-archived")
        messages.success(request, _("Candidate is %(message)s") % {"message": message})
    except (Candidate.DoesNotExist, OverflowError):
        messages.error(request, _("Candidate Does not exists."))
    if request.META.get("HTTP_HX_REQUEST") == "true":
        response = HttpResponse(status=204)
        response["HX-Trigger"] = "candidateContainerReload"
        return response
    return HorillaRedirect(request)


@login_required
@permission_required(perm="recruitment.delete_candidate")
@require_http_methods(["POST"])
@transaction.atomic
def candidate_bulk_archive(request):
    """
    This method is used to archive/un-archive bulk candidates
    """
    try:
        ids = _parse_posted_ids(request.POST.get("ids"))
    except ValueError:
        return JsonResponse({"error": "Invalid candidate IDs."}, status=400)
    state_value = request.POST.get("is_active", "").lower()
    if not ids or state_value not in {"true", "false"}:
        return JsonResponse({"error": "Invalid archive request."}, status=400)
    candidates = Candidate.objects.select_for_update().filter(id__in=ids)
    if candidates.count() != len(ids):
        return JsonResponse({"error": "Candidate not found."}, status=404)
    candidates.update(is_active=state_value == "true")
    messages.success(request, _("Selected candidates updated successfully."))
    return JsonResponse({"message": "Success", "updated": len(ids)})


@login_required
@manager_can_enter(perm="recruitment.change_stage")
@require_http_methods(["POST"])
@transaction.atomic
def remove_stage_manager(request, mid, sid):
    """
    This method is used to remove selected stage manager and also removing the  given
    permission if the employee is not exists in more stage manager or recruitment manager
    Args:
        mid : manager_id in the stage
        sid : stage_id
    """
    stage_obj = (
        Stage.objects.select_for_update()
        .select_related("recruitment_id")
        .filter(id=sid)
        .first()
    )
    manager = Employee.objects.filter(id=mid).first()
    if not stage_obj or not manager:
        return HorillaRedirect(
            request,
            message=_("No %(model_name)s found matching the query.")
            % {"model_name": "Stage" if not stage_obj else "Employee"},
        )

    if not _can_manage_recruitment(
        request,
        stage_obj.recruitment_id,
        "recruitment.change_stage",
        include_stage_managers=True,
    ):
        return _permission_denied_json()
    if not stage_obj.stage_managers.filter(pk=manager.pk).exists():
        return JsonResponse({"message": _("Stage manager not found.")}, status=404)
    stage_obj.stage_managers.remove(manager)
    transaction.on_commit(
        lambda: _notify_safely(
            request.user.employee_get,
            recipient=manager.employee_user_id,
            verb=f"You are removed from stage managers from stage {stage_obj}",
            verb_ar=f"تمت إزالتك من مديري المرحلة من المرحلة {stage_obj}",
            verb_de=f"Sie wurden als Bühnenmanager von der Stufe {stage_obj} entfernt",
            verb_es=f"Has sido eliminado/a de los gerentes de etapa de la etapa {stage_obj}",
            verb_fr=f"Vous avez été supprimé(e) en tant que responsable de l'étape {stage_obj}",
            icon="person-remove",
            redirect="",
        )
    )
    messages.success(request, _("Stage manager removed successfully."))
    stages = Stage.objects.all()
    stages = stages.filter(recruitment_id__is_active=True)
    recruitments = group_by_queryset(
        stages,
        "recruitment_id",
        request.GET.get("rpage"),
    )
    filter_obj = StageFilter()
    form = StageCreationForm()
    previous_data = request.GET.urlencode()
    return render(
        request,
        "stage/stage_group.html",
        {
            "data": paginator_qry(stages, request.GET.get("page")),
            "pd": previous_data,
            "form": form,
            "f": filter_obj,
            "recruitments": recruitments,
        },
    )


@login_required
@manager_can_enter(perm="recruitment.change_recruitment")
@require_http_methods(["POST"])
@transaction.atomic
def remove_recruitment_manager(request, mid, rid):
    """
    This method is used to remove selected manager from the recruitment,
    when remove the manager permissions also removed if the employee is not
    exists in more stage manager or recruitment manager

     Args:
        mid : employee manager_id in the recruitment
        rid : recruitment_id
    """
    recruitment_obj = Recruitment.objects.select_for_update().filter(id=rid).first()
    manager = Employee.objects.filter(id=mid).first()
    if recruitment_obj is None or manager is None:
        return JsonResponse({"message": _("Manager not found.")}, status=404)
    if not _can_manage_recruitment(
        request, recruitment_obj, "recruitment.change_recruitment"
    ):
        return _permission_denied_json()
    if not recruitment_obj.recruitment_managers.filter(pk=manager.pk).exists():
        return JsonResponse({"message": _("Recruitment manager not found.")}, status=404)
    recruitment_obj.recruitment_managers.remove(manager)
    messages.success(request, _("Recruitment manager removed successfully."))
    transaction.on_commit(
        lambda: _notify_safely(
            request.user.employee_get,
            recipient=manager.employee_user_id,
            verb=f"You are removed from recruitment manager from {recruitment_obj}",
            verb_ar=f"تمت إزالتك من وظيفة مدير التوظيف في {recruitment_obj}",
            verb_de=f"Sie wurden als Personalvermittler von {recruitment_obj} entfernt",
            verb_es=f"Has sido eliminado/a como gerente de contratación de {recruitment_obj}",
            verb_fr=f"Vous avez été supprimé(e) en tant que responsable du recrutement de {recruitment_obj}",
            icon="person-remove",
            redirect="",
        )
    )
    recruitment_queryset = Recruitment.objects.all()
    previous_data = request.GET.urlencode()
    return HttpResponse("<script> $('#applyFilter').click();</script>")

    # return render(
    #     request,
    #     "recruitment/recruitment_component.html",
    #     {
    #         "data": paginator_qry(recruitment_queryset, request.GET.get("page")),
    #         "pd": previous_data,
    #     },
    # )


@login_required
def get_template(request, obj_id=None):
    """
    This method is used to return the mail template
    """
    body = ""
    if obj_id:
        body = (
            HorillaMailTemplate.find(obj_id).body
            if HorillaMailTemplate.find(obj_id)
            else None
        )
        if not body:
            return JsonResponse({"body": None})

        template_bdy = template.Template(body)
    if request.GET.get("word"):
        word = request.GET.get("word")
        template_bdy = template.Template("{{" + word + "}}")
    candidate_id = request.GET.get("candidate_id")
    if candidate_id:
        candidate_obj = Candidate.objects.get(id=candidate_id)
        context = template.Context(
            {"instance": candidate_obj, "self": request.user.employee_get}
        )
        # body = template_bdy.render(context) or " "
    return JsonResponse({"body": body})


@login_required
@permission_required("recruitment.view_candidate")
def get_template_hint(request, obj_id=None):
    """
    This method is used to return the mail template
    """
    body = " "
    template_bdy = None
    allowed_template_words = set(MailTemplateForm().get_template_language().values())
    if obj_id:
        body = HorillaMailTemplate.objects.get(id=obj_id).body
        template_bdy = template.Template(sanitize_mail_template_body(body))
    if request.GET.get("word"):
        word = request.GET.get("word").strip()
        # Allow only known template placeholders used by the editor hints.
        # This prevents arbitrary attribute traversal through user input.
        sanitized_word_template = sanitize_mail_template_body("{{" + word + "}}")
        if word in allowed_template_words and sanitized_word_template.strip():
            template_bdy = template.Template(sanitized_word_template)
    candidate_id = request.GET.get("candidate_id")
    if candidate_id and template_bdy is not None:
        candidate_qs = Candidate.objects.filter(id=candidate_id)
        if not request.user.has_perm("recruitment.view_candidate"):
            employee = request.user.employee_get
            candidate_qs = candidate_qs.filter(
                Q(recruitment_id__recruitment_managers=employee)
                | Q(stage_id__stage_managers=employee)
            )
        candidate_obj = candidate_qs.first()
        if not candidate_obj:
            return JsonResponse({"body": " "}, status=404)
        context = template.Context(
            {"instance": candidate_obj, "self": request.user.employee_get}
        )
        body = template_bdy.render(context) or " "
    return JsonResponse({"body": body})


@login_required
def get_mail_preview(request):
    """
    Returns the mail template preview as HTML.
    """
    body = request.POST.get("body")
    if not body:
        return HttpResponse("No body provided", status=400)

    # Strip dangerous template constructs first.
    body = sanitize_mail_template_body(body)
    allowed_template_words = set(MailTemplateForm().get_template_language().values())
    body = sanitize_mail_template_placeholders(body, allowed_template_words)

    candidate_id = request.GET.get("candidate_id")
    candidate_ids = request.POST.getlist("candidates")  # 875

    # Fetch one candidate for preview if provided
    candidate_obj = None
    if candidate_id or candidate_ids:
        ids = [candidate_id] if candidate_id else candidate_ids
        candidate_obj = Candidate.objects.filter(id__in=ids).first()
        if not candidate_obj:
            return HttpResponse("Candidate not found", status=404)

    # Keep `request` in context, but only as a sanitized proxy.
    context = {
        "instance": candidate_obj,
        "model_instance": candidate_obj,
        "self": getattr(request.user, "employee_get", None),
        "request": build_safe_template_request(request),
    }

    # Render template
    rendered_body = template.Template(body).render(template.Context(context)) or " "

    # Add preview note if multiple candidates
    if candidate_ids and len(candidate_ids) > 1 and candidate_obj:
        rendered_body = (
            f"<p style='color:gray; font-size:13px;'>"
            f"Preview shown for {candidate_obj.name}. "
            f"Mail will be personalized for {len(candidate_ids)} candidates."
            f"</p>{rendered_body}"
        )

    # Wrap in styled div
    textarea_field = (
        f'<div class="oh-input oh-input--textarea" '
        f'style="border: solid .1px #dbd7d7; padding:5px;">{rendered_body}</div>'
    )

    return HttpResponse(textarea_field, content_type="text/html")
