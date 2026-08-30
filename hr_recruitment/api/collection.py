"""Method-aware HR04 collection endpoints.

Each canonical resource path is registered exactly once in Django.  The
adapter only chooses the existing, independently permissioned handler for the
HTTP method; business validation, tenant resolution and response envelopes
remain in the original endpoint modules.
"""

from django.views.decorators.http import require_http_methods

from hr_recruitment.api import campaign as campaign_api
from hr_recruitment.api import candidate as candidate_api
from hr_recruitment.api import medical_background as medical_background_api
from hr_recruitment.api import plan as plan_api
from hr_recruitment.api import proposed_hire as proposed_hire_api


@require_http_methods(["GET", "POST"])
def proposed_hire_collection(request):
    if request.method == "GET":
        return proposed_hire_api.proposed_hire_list(request)
    return proposed_hire_api.create_proposed_hire(request)


@require_http_methods(["GET", "POST"])
def medical_collection(request, application_id):
    if request.method == "GET":
        return medical_background_api.medical_summary(request, application_id)
    return medical_background_api.record_medical(request, application_id)


@require_http_methods(["GET", "POST"])
def background_collection(request, application_id):
    if request.method == "GET":
        return medical_background_api.background_summary(request, application_id)
    return medical_background_api.record_background(request, application_id)


@require_http_methods(["GET", "POST"])
def candidate_collection(request):
    if request.method == "GET":
        return candidate_api.list_candidates(request)
    return candidate_api.create_candidate(request)


@require_http_methods(["GET", "POST"])
def campaign_collection(request):
    if request.method == "GET":
        return campaign_api.list_campaigns(request)
    return campaign_api.create_campaign(request)


@require_http_methods(["GET", "POST"])
def plan_collection(request):
    if request.method == "GET":
        return plan_api.list_plans(request)
    return plan_api.create_plan(request)
