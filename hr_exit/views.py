from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from .api import HrExitAccessError, resolve_request_tenant

SECTIONS={"overview":"离退总览","cases":"离校审批","handover":"交接与结算","retirement":"退休预审","effects":"跨域生效协同","archive":"档案与历史事实"}

@ensure_csrf_cookie
def workspace(request, section="overview"):
    try: tenant_id=resolve_request_tenant(request)
    except HrExitAccessError as exc: return render(request,"hr_exit/workspace.html",{"access_error":str(exc),"section":section,"section_title":SECTIONS.get(section,"退休离校")},status=403)
    return render(request,"hr_exit/workspace.html",{"tenant_id":tenant_id,"section":section,"section_title":SECTIONS.get(section,"退休离校")})
