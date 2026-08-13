from datetime import date

from django.test import TestCase, override_settings

from hr_data.models import (
    AsOfEvidenceSnapshot,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
)
from hr_data.services.asof_service import (
    AsOfReconstructionError,
    AsOfReconstructionService,
)


PROVIDER_CALLS = []


def hr03_ok_provider(**kwargs):
    PROVIDER_CALLS.append(("HR03", kwargs))
    return {"status": "OK", "sourceVersion": "hr03-v7", "evidenceHash": "a" * 64}


def hr13_ok_provider(**kwargs):
    PROVIDER_CALLS.append(("HR13", kwargs))
    return {"status": "OK", "sourceVersion": "hr13-v3", "evidenceHash": "b" * 64}


def stale_provider(**kwargs):
    PROVIDER_CALLS.append(("STALE", kwargs))
    return {"status": "STALE", "sourceVersion": "v2", "evidenceHash": "c" * 64}


def failing_provider(**_kwargs):
    raise RuntimeError("provider exploded")


def invalid_provider(**_kwargs):
    return {"status": "OK", "sourceVersion": "v1"}


class AsOfReconstructionServiceTests(TestCase):
    def setUp(self):
        PROVIDER_CALLS.clear()

    @staticmethod
    def _population(*, tenant_id=77, code="ACTIVE_STAFF", sources=None, content_hash="d" * 64):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=tenant_id,
            population_code=code,
            name="在职教职工",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=sources or ["HR03", "HR13"],
            version_no=1,
            content_hash=content_hash,
        )

    @override_settings(
        HR18_ASOF_PROVIDERS={
            "HR03": "hr_data.tests.test_asof_service.hr03_ok_provider",
            "HR13": "hr_data.tests.test_asof_service.hr13_ok_provider",
        }
    )
    def test_all_required_sources_ok_create_complete_immutable_evidence(self):
        self._population()
        service = AsOfReconstructionService(77, actor_user_id=9)

        outcome = service.reconstruct(
            evidence_no="E-20260801-001",
            definition_kind="population",
            definition_code="active_staff",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertTrue(outcome.created)
        evidence = outcome.evidence
        self.assertEqual(evidence.definition_kind, AsOfEvidenceSnapshot.DefinitionKind.POPULATION)
        self.assertEqual(evidence.status, AsOfEvidenceSnapshot.Status.COMPLETE)
        self.assertEqual(evidence.source_statuses_json, {"HR03": "OK", "HR13": "OK"})
        self.assertEqual(evidence.blocked_domains_json, [])
        self.assertEqual(evidence.provider_versions_json["HR03"], "hr03-v7")
        self.assertEqual(evidence.provider_evidence_hashes_json["HR13"], "b" * 64)
        self.assertEqual(len(evidence.evidence_hash), 64)
        self.assertEqual(len(PROVIDER_CALLS), 2)
        self.assertEqual(PROVIDER_CALLS[0][1]["tenant_id"], 77)
        self.assertEqual(PROVIDER_CALLS[0][1]["as_of_date"], date(2026, 8, 1))

        replay = service.reconstruct(
            evidence_no="E-20260801-001",
            definition_kind="POPULATION",
            definition_code="ACTIVE_STAFF",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.evidence.id, evidence.id)
        self.assertEqual(len(PROVIDER_CALLS), 2)

        evidence.provider_evidence_hashes_json = {"HR03": "f" * 64}
        with self.assertRaisesRegex(ValueError, "HR18_ASOF_EVIDENCE_IMMUTABLE"):
            evidence.save()

    @override_settings(
        HR18_ASOF_PROVIDERS={
            "HR03": "hr_data.tests.test_asof_service.hr03_ok_provider",
        }
    )
    def test_missing_required_provider_is_unavailable_not_zero_or_complete(self):
        self._population()
        evidence = AsOfReconstructionService(77).reconstruct(
            evidence_no="E-MISSING",
            definition_kind="POPULATION",
            definition_code="ACTIVE_STAFF",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        ).evidence

        self.assertEqual(evidence.status, AsOfEvidenceSnapshot.Status.UNAVAILABLE)
        self.assertEqual(evidence.source_statuses_json["HR13"], "UNAVAILABLE")
        self.assertEqual(evidence.blocked_domains_json, ["HR13"])
        self.assertEqual(evidence.provider_evidence_hashes_json["HR13"], "")

    @override_settings(
        HR18_ASOF_PROVIDERS={
            "HR03": "hr_data.tests.test_asof_service.hr03_ok_provider",
            "HR13": "hr_data.tests.test_asof_service.stale_provider",
        }
    )
    def test_stale_source_is_partial_and_blocks_formal_completeness(self):
        self._population()
        evidence = AsOfReconstructionService(77).reconstruct(
            evidence_no="E-STALE",
            definition_kind="POPULATION",
            definition_code="ACTIVE_STAFF",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        ).evidence
        self.assertEqual(evidence.status, AsOfEvidenceSnapshot.Status.PARTIAL)
        self.assertEqual(evidence.blocked_domains_json, ["HR13"])

    @override_settings(
        HR18_ASOF_PROVIDERS={
            "HR03": "hr_data.tests.test_asof_service.failing_provider",
        }
    )
    def test_provider_exception_becomes_error_evidence(self):
        self._population(sources=["HR03"])
        evidence = AsOfReconstructionService(77).reconstruct(
            evidence_no="E-ERROR",
            definition_kind="POPULATION",
            definition_code="ACTIVE_STAFF",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        ).evidence
        self.assertEqual(evidence.status, AsOfEvidenceSnapshot.Status.ERROR)
        self.assertEqual(evidence.source_statuses_json, {"HR03": "ERROR"})

    @override_settings(
        HR18_ASOF_PROVIDERS={
            "HR03": "hr_data.tests.test_asof_service.invalid_provider",
        }
    )
    def test_provider_ok_without_hash_is_contract_error_not_complete(self):
        self._population(sources=["HR03"])
        evidence = AsOfReconstructionService(77).reconstruct(
            evidence_no="E-BAD-CONTRACT",
            definition_kind="POPULATION",
            definition_code="ACTIVE_STAFF",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        ).evidence
        self.assertEqual(evidence.status, AsOfEvidenceSnapshot.Status.ERROR)
        self.assertEqual(evidence.provider_versions_json["HR03"], "")

    def test_cross_tenant_definition_and_bad_definition_hash_fail_closed(self):
        self._population(tenant_id=88)
        with self.assertRaises(AsOfReconstructionError) as ctx:
            AsOfReconstructionService(77).reconstruct(
                evidence_no="E-XTENANT",
                definition_kind="POPULATION",
                definition_code="ACTIVE_STAFF",
                definition_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertEqual(ctx.exception.code, "ASOF_DEFINITION_NOT_FOUND")

        self._population(tenant_id=77, content_hash="")
        with self.assertRaises(AsOfReconstructionError) as ctx:
            AsOfReconstructionService(77).reconstruct(
                evidence_no="E-NOHASH",
                definition_kind="POPULATION",
                definition_code="ACTIVE_STAFF",
                definition_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertEqual(ctx.exception.code, "ASOF_DEFINITION_HASH_INVALID")
        self.assertFalse(AsOfEvidenceSnapshot.objects.filter(evidence_no="E-NOHASH").exists())

    @override_settings(
        HR18_ASOF_PROVIDERS={
            "HR03": "hr_data.tests.test_asof_service.hr03_ok_provider",
        }
    )
    def test_definition_kind_disambiguates_same_code_and_evidence_no_is_immutable(self):
        self._population(code="HEADCOUNT", sources=["HR03"])
        MetricDefinitionVersion.objects.create(
            tenant_id=77,
            metric_code="HEADCOUNT",
            name="人数",
            value_type="INTEGER",
            population_code="HEADCOUNT",
            expression='{"dslVersion":"1","op":"COUNT","field":null,"populationVersion":1}',
            source_domains=["HR03"],
            version_no=1,
            content_hash="e" * 64,
        )
        service = AsOfReconstructionService(77)
        population = service.reconstruct(
            evidence_no="E-KIND",
            definition_kind="POPULATION",
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        ).evidence
        self.assertEqual(population.definition_kind, "POPULATION")

        with self.assertRaises(AsOfReconstructionError) as ctx:
            service.reconstruct(
                evidence_no="E-KIND",
                definition_kind="METRIC",
                definition_code="HEADCOUNT",
                definition_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertEqual(ctx.exception.code, "ASOF_EVIDENCE_IDEMPOTENCY_CONFLICT")
