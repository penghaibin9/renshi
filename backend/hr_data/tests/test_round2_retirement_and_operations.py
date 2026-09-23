import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from django.db import connection, DatabaseError, transaction
from django.utils import timezone
from hr_staff.tests.round2_support import MySQLRound2Case
from hr_exit.models import RetirementFact
from hr_data.services.formal_fact_chain_service import FormalFactAsOfEvaluationService
from hr_data.services.formal_fact_evaluation_service import HR16_SPEC
from hr_data.services.operational_snapshot_service import OperationalSnapshotService
from hr_data.operational_models import OperationalSnapshot

class Round2DataMySQLTests(MySQLRound2Case):
    def fact(self,when,status="EFFECTIVE",previous=None,tenant=None):
        fact=RetirementFact(tenant_id=tenant or self.tenant,fact_no="R2-"+uuid.uuid4().hex,
            person_id=self.person.id,exit_fact_id=uuid.uuid4(),retirement_type="FLEX_DELAY",
            statutory_date=date(2026,11,1),effective_date=when,status=status,
            supersedes_fact_id=previous.id if previous else None,evidence_ref="fixture:sealed",
            sealed_at=timezone.now())
        fact.content_hash=fact.calculate_content_hash();fact.save();return fact
    def population(self):
        return SimpleNamespace(predicate_json={"field":"retirement.retirementType","op":"eq","value":"FLEX_DELAY"})

    def test_retirement_history_uses_terminal_fact_at_requested_date(self):
        first=self.fact(date(2027,5,1));self.fact(date(2027,6,1),"REVOKED",first)
        service=FormalFactAsOfEvaluationService(self.tenant)
        self.assertEqual(service._count(self.population(),HR16_SPEC,date(2027,5,20)),1)
        self.assertEqual(service._count(self.population(),HR16_SPEC,date(2027,6,1)),0)

    def test_other_school_retirement_does_not_enter_count(self):
        self.fact(date(2027,5,1),tenant=self.tenant+100000)
        self.assertEqual(FormalFactAsOfEvaluationService(self.tenant)._count(self.population(),HR16_SPEC,date(2027,5,20)),0)

    def test_observation_contains_twenty_explicit_source_states(self):
        result=OperationalSnapshotService(self.tenant,self.reviewer.pk).observe()
        self.assertEqual(len(result["items"]),20)
        self.assertFalse(result["atomicCrossDomainAsOf"])
        self.assertEqual(result["temporalMode"],"OBSERVED_WINDOW")
        self.assertTrue(all(row["sourceStatus"] in {"OK","UNAVAILABLE","ERROR"} for row in result["items"]))

    def test_snapshot_replay_does_not_refetch_or_rewrite_payload(self):
        service=OperationalSnapshotService(self.tenant,self.reviewer.pk)
        first,created=service.capture("round2-snapshot-001")
        with patch.object(service,"observe",side_effect=AssertionError("No recapture on replay")):
            second,replayed=service.capture("round2-snapshot-001")
        self.assertTrue(created);self.assertFalse(replayed);self.assertEqual(first.pk,second.pk)
        self.assertEqual(first.evidence_hash,second.compute_hash())

    def test_frozen_snapshot_cannot_be_changed_in_mysql(self):
        snapshot,_=OperationalSnapshotService(self.tenant,self.reviewer.pk).capture("round2-seal-001")
        with self.assertRaises(DatabaseError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute("UPDATE hr18_operational_snapshot SET catalog_version=%s WHERE id=%s",["tampered",snapshot.id.hex])
        self.assertEqual(OperationalSnapshot.objects.get(pk=snapshot.pk).evidence_hash,snapshot.evidence_hash)
