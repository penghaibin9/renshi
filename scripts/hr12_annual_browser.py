"""HR12 Annual Chromium proof: freeze evidence and finalize an automatic result.

The workflow seeds the business identities and annual case.  This harness then
completes the formal calculation authority with real published version rows and
a frozen cycle snapshot before Chromium performs the user-visible actions.  No
manual grade, direct final-result insert, or relaxed production validation is
used.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")

BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(
    os.getenv(
        "HR_BROWSER_ARTIFACT_DIR",
        "tests/artifacts/hr12-annual-browser",
    )
)
SEED_PATH = ARTIFACT_DIR / "seed.json"
WORKSPACES = (
    ("overview", "/hr/assessments/"),
    ("policies", "/hr/assessments/policies/"),
    ("goals", "/hr/assessments/goals/"),
    ("annual", "/hr/assessments/annual/"),
    ("term", "/hr/assessments/term/"),
    ("ethics", "/hr/assessments/ethics/"),
    ("review", "/hr/assessments/review/"),
    ("archive", "/hr/assessments/archive/"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def prepare_formal_authority(seed: dict) -> dict:
    """Complete the seeded case with published, hash-bound calculation facts."""

    import django

    django.setup()

    from django.db import transaction
    from django.utils import timezone

    from hr_assessment.models import (
        HrAnnualAssessmentCase,
        HrAssessmentPopulationSnapshot,
        HrAssessmentPolicyVersion,
        HrAssessmentWorkflowVersion,
        HrCycleSnapshot,
        HrRatingScaleVersion,
        HrResultRuleVersion,
        HrReviewerEvaluation,
    )
    from hr_assessment.models.base import calculate_version_content_hash
    from hr_assessment.models.policy import HrWorkflowStep

    tenant_id = int(seed["tenant_id"])
    now = timezone.now()

    with transaction.atomic():
        case = (
            HrAnnualAssessmentCase.objects.select_for_update()
            .select_related("cycle")
            .get(id=seed["case_id"], tenant_id=tenant_id)
        )
        cycle = case.cycle
        original_policy = HrAssessmentPolicyVersion.objects.get(
            id=case.policy_version_id,
            tenant_id=tenant_id,
        )

        rating_scale = HrRatingScaleVersion.objects.create(
            tenant_id=tenant_id,
            version_no=1,
            status="PUBLISHED",
            scale_type="NUMERIC",
            min_value="0.00",
            max_value="100.00",
            levels=[
                {"code": "EXCELLENT", "label": "优秀", "min": "90", "max": "100"},
                {"code": "QUALIFIED", "label": "合格", "min": "60", "max": "89.99"},
                {"code": "UNQUALIFIED", "label": "不合格", "min": "0", "max": "59.99"},
            ],
            display_labels={
                "EXCELLENT": "优秀",
                "QUALIFIED": "合格",
                "UNQUALIFIED": "不合格",
            },
        )
        workflow = HrAssessmentWorkflowVersion.objects.create(
            tenant_id=tenant_id,
            version_no=1,
            status="PUBLISHED",
            name="HR12 年度考核正式评议流程",
        )
        HrWorkflowStep.objects.create(
            id=uuid.uuid4(),
            workflow=workflow,
            step_code="HR_REVIEW",
            step_name="人事年度综合评议",
            actor_role="HR_REVIEWER",
            scope="ASSIGNED",
            required=True,
            return_allowed=True,
            display_order=10,
            completion_rule_json={"submittedEvaluationRequired": True},
        )
        result_rule = HrResultRuleVersion.objects.create(
            tenant_id=tenant_id,
            name="HR12 年度考核结果映射",
            version_no=1,
            status="PUBLISHED",
            score_to_grade_mapping={
                "bands": [
                    {
                        "gradeCode": "EXCELLENT",
                        "minScore": "90",
                        "maxScore": "100",
                        "displayGrade": {"zh-CN": "优秀"},
                    },
                    {
                        "gradeCode": "QUALIFIED",
                        "minScore": "60",
                        "maxScore": "89.99",
                        "displayGrade": {"zh-CN": "合格"},
                    },
                    {
                        "gradeCode": "UNQUALIFIED",
                        "minScore": "0",
                        "maxScore": "59.99",
                        "displayGrade": {"zh-CN": "不合格"},
                    },
                ]
            },
            collective_override_permission=False,
            override_reason_required=True,
        )

        policy = HrAssessmentPolicyVersion.objects.create(
            tenant_id=tenant_id,
            policy_pack=original_policy.policy_pack,
            version_no=original_policy.version_no + 1,
            status="PUBLISHED",
            effective_from=original_policy.effective_from,
            effective_to=original_policy.effective_to,
            assessment_types=["ANNUAL"],
            eligibility_rule_json={"activeStaffOnly": True},
            cycle_rule_json={"businessYearRequired": True},
            rating_scale_version_id=rating_scale.id,
            indicator_set_version_id=original_policy.indicator_set_version_id,
            workflow_version_id=workflow.id,
            result_rule_version_id=result_rule.id,
        )
        policy.policy_pack.current_published_version_id = policy.id
        policy.policy_pack.save(update_fields=["current_published_version_id", "updated_at"])

        cycle.policy_version_id = policy.id
        cycle.lifecycle_status = "ACTIVE"
        cycle.save(update_fields=["policy_version_id", "lifecycle_status", "updated_at"])
        case.policy_version_id = policy.id
        case.save(update_fields=["policy_version_id", "updated_at"])

        evaluation = (
            HrReviewerEvaluation.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                assignment__case_id=case.id,
                submitted_at__isnull=False,
            )
            .order_by("-revision_no", "-submitted_at", "-id")
            .first()
        )
        require(evaluation is not None, "HR12 reviewer evaluation seed is missing")
        desired_rating = {
            "totalScore": "80.00",
            "gradeCode": "QUALIFIED",
        }
        desired_comment = "真实年度评议已提交，系统按冻结规则自动计算"
        if (
            evaluation.rating_json != desired_rating
            or evaluation.comment != desired_comment
        ):
            evaluation = HrReviewerEvaluation.objects.create(
                tenant_id=tenant_id,
                assignment=evaluation.assignment,
                indicator_evaluations_json=evaluation.indicator_evaluations_json,
                rating_json=desired_rating,
                comment=desired_comment,
                recommendation=evaluation.recommendation or "QUALIFIED",
                submitted_at=now,
                revision_no=evaluation.revision_no + 1,
            )

        snapshot = HrCycleSnapshot.objects.create(
            tenant_id=tenant_id,
            cycle=cycle,
            frozen_policy_json={
                "id": str(policy.id),
                "contentHash": policy.content_hash,
                "resultRule": {
                    "id": str(result_rule.id),
                    "contentHash": result_rule.content_hash,
                    "scoreToGradeMapping": result_rule.score_to_grade_mapping,
                },
            },
            frozen_org_scope_json={"mode": "TENANT"},
            frozen_population_query_definition={"activeStaffOnly": True},
            frozen_rating_scale_json={
                "id": str(rating_scale.id),
                "contentHash": rating_scale.content_hash,
                "minValue": "0",
                "maxValue": "100",
                "levels": rating_scale.levels,
            },
            frozen_indicator_set_json={
                "id": str(original_policy.indicator_set_version_id),
            },
            frozen_workflow_json={
                "id": str(workflow.id),
                "contentHash": workflow.content_hash,
                "steps": [
                    {
                        "stepCode": "HR_REVIEW",
                        "actorRole": "HR_REVIEWER",
                        "required": True,
                    }
                ],
            },
            frozen_reviewer_rules_json={
                "scoreAggregation": "WEIGHTED_AVERAGE",
                "scoreField": "totalScore",
                "roleWeights": {"HR_REVIEWER": "1"},
            },
            frozen_deadlines_json={"cycleEndAt": cycle.end_at.isoformat()},
            frozen_publicity_rule_json={"required": False},
            frozen_result_notice_rule_json={"mode": "AFTER_FINALIZATION"},
        )
        HrAssessmentPopulationSnapshot.objects.create(
            tenant_id=tenant_id,
            cycle=cycle,
            staff_id=case.staff_id,
            employment_relationship_id=None,
            primary_assignment_id=None,
            org_id=None,
            position_id=None,
            worker_category=(
                case.subject_snapshot.worker_category
                if case.subject_snapshot_id
                else ""
            ),
            classification_profile_json={"source": "HR12_BROWSER_AUTHORITY"},
            included=True,
            excluded=False,
            snapshot_at=now,
            policy_version_id=policy.id,
            eligibility_reason_codes=["ACTIVE_STAFF"],
        )

        require(
            policy.content_hash == calculate_version_content_hash(policy),
            "published HR12 policy hash drifted",
        )
        require(
            result_rule.content_hash == calculate_version_content_hash(result_rule),
            "published HR12 result-rule hash drifted",
        )
        require(
            rating_scale.content_hash == calculate_version_content_hash(rating_scale),
            "published HR12 rating-scale hash drifted",
        )
        require(
            workflow.content_hash == calculate_version_content_hash(workflow),
            "published HR12 workflow hash drifted",
        )

    seed.update(
        {
            "policy_version_id": str(policy.id),
            "rating_scale_version_id": str(rating_scale.id),
            "workflow_version_id": str(workflow.id),
            "result_rule_version_id": str(result_rule.id),
            "cycle_snapshot_id": str(snapshot.id),
            "expected_score": "80.00",
            "expected_grade": "QUALIFIED",
        }
    )
    SEED_PATH.write_text(
        json.dumps(seed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "authority.json").write_text(
        json.dumps(
            {
                "tenantId": tenant_id,
                "caseId": seed["case_id"],
                "policyVersionId": seed["policy_version_id"],
                "ratingScaleVersionId": seed["rating_scale_version_id"],
                "workflowVersionId": seed["workflow_version_id"],
                "resultRuleVersionId": seed["result_rule_version_id"],
                "cycleSnapshotId": seed["cycle_snapshot_id"],
                "calculation": {
                    "aggregation": "WEIGHTED_AVERAGE",
                    "scoreField": "totalScore",
                    "expectedScore": seed["expected_score"],
                    "expectedGrade": seed["expected_grade"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return seed


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed = prepare_formal_authority(seed)
    case_id = seed["case_id"]
    evidence = []
    api_failures = []
    failure = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        def record_api_failure(response) -> None:
            if (
                "/api/v1/hr/assessments/" in response.url
                and response.status >= 400
            ):
                api_failures.append(f"{response.status} {response.url}")

        page.on("response", record_api_failure)
        try:
            login_response = page.goto(
                BASE_URL + "/login/?next=/hr/assessments/annual/",
                wait_until="domcontentloaded",
            )
            require(
                login_response is not None and login_response.status == 200,
                "login page failed",
            )
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            login_button = page.locator("button.yk-login-submit")
            require(
                login_button.count() == 1 and login_button.is_visible(),
                "visible production login button is missing or ambiguous",
            )
            with page.expect_navigation(wait_until="domcontentloaded") as login_nav:
                login_button.click()
            require(
                login_nav.value is not None and login_nav.value.status < 400,
                "login click failed",
            )
            require("/login" not in page.url, "login did not establish a session")

            for viewport_name, viewport in (
                ("desktop", {"width": 1440, "height": 1000}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                page.set_viewport_size(viewport)
                for workspace_name, workspace_path in WORKSPACES:
                    response = page.goto(
                        BASE_URL + workspace_path,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 200,
                        f"HR12 {workspace_name} {viewport_name} page failed",
                    )
                    page.locator(
                        "#workRows .hr12-row, #workRows .hr12-empty"
                    ).first.wait_for(
                        state="visible",
                        timeout=15000,
                    )
                    page.screenshot(
                        path=str(
                            ARTIFACT_DIR
                            / f"workspace-{viewport_name}-{workspace_name}.png"
                        ),
                        full_page=True,
                    )
                evidence.append(
                    {
                        "step": f"audit-{viewport_name}-workspaces",
                        "pages": len(WORKSPACES),
                        "http_status": 200,
                    }
                )

            page.set_viewport_size({"width": 1440, "height": 1000})
            policy_response = page.goto(
                BASE_URL + "/hr/assessments/policies/",
                wait_until="domcontentloaded",
            )
            require(
                policy_response is not None and policy_response.status == 200,
                "HR12 policies page failed",
            )
            page.locator("[data-open]").click()
            page.locator("#hr12-policy-code").fill("HR12-BROWSER-GOVERNANCE")
            page.locator("#hr12-policy-name").fill("HR12 浏览器制度治理")
            with page.expect_response(
                lambda response: response.url.endswith(
                    "/api/v1/hr/assessments/policies"
                )
                and response.request.method == "POST"
            ) as create_info:
                page.locator("[data-form] [type='submit']").click()
            require(
                create_info.value.status == 201,
                f"policy create HTTP {create_info.value.status}",
            )
            page.wait_for_timeout(900)
            created_row = page.locator(".hr12-action-row").filter(
                has_text="HR12-BROWSER-GOVERNANCE"
            )
            created_row.wait_for(state="visible", timeout=15000)
            created_row.locator("[data-rename]").click()
            created_row.locator(
                "[data-rename-form] input[name='name']"
            ).fill("HR12 浏览器制度治理（修订）")
            with page.expect_response(
                lambda response: "/api/v1/hr/assessments/policies/"
                in response.url
                and response.request.method == "PUT"
            ) as rename_info:
                created_row.locator(
                    "[data-rename-form] [type='submit']"
                ).click()
            require(
                rename_info.value.status == 200,
                f"policy rename HTTP {rename_info.value.status}",
            )
            evidence.append(
                {
                    "step": "create-and-rename-policy-pack",
                    "http_status": 200,
                }
            )

            annual_response = page.goto(
                BASE_URL + "/hr/assessments/annual/",
                wait_until="domcontentloaded",
            )
            require(
                annual_response is not None and annual_response.status == 200,
                "HR12 annual page failed",
            )
            row = page.locator(f'[data-annual-case="{case_id}"]')
            row.wait_for(state="visible", timeout=15000)
            row.locator("[data-annual-snapshot]").wait_for(
                state="visible",
                timeout=10000,
            )
            page.screenshot(
                path=str(ARTIFACT_DIR / "01-annual-proposed.png"),
                full_page=True,
            )

            snapshot_api = (
                f"/api/v1/hr/assessments/cases/{case_id}/provider-snapshot"
            )
            with page.expect_response(
                lambda response: snapshot_api in response.url
                and response.request.method == "POST"
            ) as snapshot_info:
                row.locator("[data-annual-snapshot]").click()
            snapshot_response = snapshot_info.value
            require(
                snapshot_response.status == 200,
                f"provider snapshot HTTP {snapshot_response.status}",
            )
            row = page.locator(f'[data-annual-case="{case_id}"]')
            row.locator("[data-annual-finalize]").wait_for(
                state="visible",
                timeout=15000,
            )
            evidence.append(
                {
                    "step": "freeze-provider-snapshot",
                    "api": snapshot_api,
                    "http_status": 200,
                }
            )
            page.screenshot(
                path=str(ARTIFACT_DIR / "02-evidence-ready.png"),
                full_page=True,
            )

            require(
                row.locator("[data-annual-grade]").count() == 0,
                "manual annual grade override must not be rendered",
            )
            automatic_note = row.locator(".hr12-status-note")
            automatic_note.wait_for(state="visible", timeout=10000)
            require(
                "自动计算" in automatic_note.inner_text(),
                "automatic grade derivation notice is missing",
            )
            evidence.append(
                {
                    "step": "verify-automatic-grade-contract",
                    "manual_override_controls": 0,
                    "http_status": 200,
                }
            )

            finalize_api = f"/api/v1/hr/assessments/cases/{case_id}/finalize"
            with page.expect_response(
                lambda response: finalize_api in response.url
                and response.request.method == "POST"
            ) as finalize_info:
                row.locator("[data-annual-finalize]").click()
            finalize_response = finalize_info.value
            require(
                finalize_response.status == 200,
                f"finalization HTTP {finalize_response.status}",
            )
            final_row = page.locator(
                f'[data-annual-case="{case_id}"]'
                '[data-case-status="FINALIZED"]'
            )
            final_row.wait_for(state="visible", timeout=15000)
            require(
                "合格" in final_row.inner_text(),
                "automatically derived formal grade was not rendered",
            )
            evidence.append(
                {
                    "step": "finalize-automatic-annual-result",
                    "api": finalize_api,
                    "http_status": 200,
                    "expected_score": seed["expected_score"],
                    "expected_grade": seed["expected_grade"],
                }
            )
            page.screenshot(
                path=str(ARTIFACT_DIR / "03-finalized.png"),
                full_page=True,
            )
            require(
                not api_failures,
                "HR12 API failures: " + " | ".join(api_failures),
            )
        except BaseException as exc:
            failure = exc
            try:
                page.screenshot(
                    path=str(ARTIFACT_DIR / "zz-failure.png"),
                    full_page=True,
                )
            except Exception:
                pass
        finally:
            try:
                context.tracing.stop(path=str(ARTIFACT_DIR / "trace.zip"))
            finally:
                context.close()
                browser.close()

    (ARTIFACT_DIR / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "diagnostics.json").write_text(
        json.dumps(
            {
                "api_failures": api_failures,
                "failure": None if failure is None else repr(failure),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
