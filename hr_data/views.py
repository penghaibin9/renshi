from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from .api import HrDataAccessError, resolve_request_tenant

SECTIONS={"overview":"人事数据总览","metrics":"指标口径中心","quality":"数据质量中心","exchange":"数据交换","submissions":"正式报送","corrections":"回执与更正"}

@ensure_csrf_cookie
def workspace(request, section="overview"):
    try: tenant_id=resolve_request_tenant(request)
    except HrDataAccessError as exc: return render(request,"hr_data/workspace.html",{"access_error":str(exc),"section":section,"section_title":SECTIONS.get(section,"人事数据中心")},status=403)
    return render(request,"hr_data/workspace.html",{"tenant_id":tenant_id,"section":section,"section_title":SECTIONS.get(section,"人事数据中心")})
