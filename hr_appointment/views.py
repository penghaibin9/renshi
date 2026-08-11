from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from .api import HrAppointmentAccessError, resolve_request_tenant

SECTIONS={"overview":"聘任总览","supply":"岗位额度快照","applications":"竞聘申报","review":"评议与排序","publicity":"拟聘公示","terms":"聘期与变更"}

@ensure_csrf_cookie
def workspace(request, section="overview"):
    try: tenant_id=resolve_request_tenant(request)
    except HrAppointmentAccessError as exc: return render(request,"hr_appointment/workspace.html",{"access_error":str(exc),"section":section,"section_title":SECTIONS.get(section,"岗位聘任")},status=403)
    return render(request,"hr_appointment/workspace.html",{"tenant_id":tenant_id,"section":section,"section_title":SECTIONS.get(section,"岗位聘任")})
