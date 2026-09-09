"""Server-rendered first-structure workbench; no browser-side business authority."""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from base.school_management import profile_complete, profile_values
from base.settings_center import _selected_company
from hr_structure.services.organization_change import Hr02ServiceError
from hr_structure.services.position import PositionServiceError
from hr_structure.initialization_forms import InitialStructureForm
from hr_structure.models import HrOrganization, HrPosition, HrPostCatalog
from hr_structure.services.initialization import (
    StructureSetupConflict, can_initialize, initialization_for, initialize_structure,
)

PROOF_SALT = "hr02.initial-structure.v1"
READ_PERMISSIONS = (
    "base.view_company", "hr.structure.organization.view",
    "hr.structure.post_catalog.view", "hr.structure.position.view",
)


def setup_proof(user, school):
    return signing.dumps({"actor": user.pk, "school": school.pk, "name": school.company,
                          "date": timezone.localdate().isoformat()}, salt=PROOF_SALT)


def _verify_proof(request, school):
    try:
        value = signing.loads(request.POST.get("setup_proof", ""), salt=PROOF_SALT, max_age=1800)
        if (not isinstance(value, dict) or value.get("actor") != request.user.pk
                or value.get("school") != school.pk or not isinstance(value.get("name"), str)):
            raise ValueError
        value["date"] = date.fromisoformat(value["date"])
        return value
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise StructureSetupConflict("办理凭证已过期或不属于当前学校，请刷新页面后核对。") from None


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def initial_structure(request):
    school = _selected_company(request)
    school.refresh_from_db()
    if not all(request.user.has_perm(code) for code in READ_PERMISSIONS):
        raise PermissionDenied("需要本校组织、岗位目录和岗位查看权限。")
    editable = can_initialize(request.user, school.pk)
    form = InitialStructureForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST":
        if not editable:
            raise PermissionDenied("当前账号没有首次建立组织和岗位的权限。")
        if form.is_valid():
            try:
                proof = _verify_proof(request, school)
                _, created = initialize_structure(
                    tenant_id=school.pk, actor=request.user, values=request.POST,
                    expected_school_name=proof["name"], effective_date=proof["date"],
                )
            except StructureSetupConflict as exc:
                form.add_error(None, str(exc))
                status = 409
            except IntegrityError:
                form.add_error(None, "相同编码已被另一次操作使用。本次未保留部分数据，请刷新后核对。")
                status = 409
            except (Hr02ServiceError, PositionServiceError) as exc:
                form.add_error(None, exc.message)
                status = exc.http_status
            except ValidationError:
                form.add_error(None, "资料校验未通过，请核对表单后重试。")
                status = 400
            else:
                messages.success(request, "初始组织与岗位已建立。" if created else "该次办理已完成，未重复创建。")
                return redirect("hr-structure-initial-setup")
        else:
            status = 400
    receipt = initialization_for(school.pk)
    existing = any(model.objects.filter(tenant_id=school.pk).exists()
                   for model in (HrOrganization, HrPostCatalog, HrPosition))
    complete = profile_complete(profile_values(school))
    return render(request, "hr/structure/initial_setup.html", {
        "school": school, "setup_form": form, "setup_proof": setup_proof(request.user, school),
        "receipt": receipt, "can_initialize": editable, "profile_complete": complete,
        "has_existing_structure": existing, "today": timezone.localdate(),
        "can_view_staff": request.user.has_perm("hr.staff.view"),
    }, status=status)
