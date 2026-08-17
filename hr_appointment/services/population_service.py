"""Freeze an HR14 batch population from effective-dated HR03 authority facts."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_appointment.models import AppointmentBatch
from hr_appointment.population_models import (
    AppointmentPopulationMemberSnapshot,
    AppointmentPopulationSnapshot,
)
from hr_staff.constants import AssignmentStatus, AssignmentType, RelationshipStatus
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment


class AppointmentPopulationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AppointmentPopulationService:
    SOURCE_VERSION = "hr03-employment-assignment-v1"

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentPopulationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_batch(self, batch_id) -> AppointmentBatch:
        batch = (
            AppointmentBatch.objects.select_for_update()
            .filter(id=batch_id, tenant_id=self.tenant_id)
            .first()
        )
        if batch is None:
            raise AppointmentPopulationError(
                "APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found"
            )
        return batch

    @staticmethod
    def _hash_payload(payload) -> str:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _active_relationship_rows(self, as_of_date: date):
        return list(
            HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id,
                status=RelationshipStatus.ACTIVE,
                effective_from__lte=as_of_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .values(
                "id",
                "version",
                "relationship_type",
                "employment_type",
                "effective_from",
                "effective_to",
                "staff_id_id",
                "staff_id__person_id_id",
                "staff_id__staff_category_code",
            )
            .order_by("staff_id__person_id_id", "effective_from", "id")
        )

    def _active_primary_assignment_rows(self, relationship_ids, as_of_date: date):
        if not relationship_ids:
            return []
        return list(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id_id__in=relationship_ids,
                assignment_type=AssignmentType.PRIMARY,
                status=AssignmentStatus.ACTIVE,
                effective_from__lte=as_of_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .values(
                "id",
                "version",
                "employment_relationship_id_id",
                "organization_id_id",
                "position_id_id",
                "post_catalog_id_id",
                "assignment_role_code",
                "effective_from",
                "effective_to",
            )
            .order_by("employment_relationship_id_id", "effective_from", "id")
        )

    @transaction.atomic
    def freeze_from_hr03(
        self,
        batch_id,
        *,
        as_of_date: Optional[date] = None,
    ) -> AppointmentPopulationSnapshot:
        batch = self._lock_batch(batch_id)
        existing = (
            AppointmentPopulationSnapshot.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, batch=batch)
            .first()
        )
        if existing is not None:
            if as_of_date is not None and existing.as_of_date != as_of_date:
                raise AppointmentPopulationError(
                    "APPOINTMENT_POPULATION_IDEMPOTENCY_CONFLICT",
                    "batch already owns a population frozen at a different as-of date",
                )
            return existing

        if batch.status not in {
            AppointmentBatch.Status.DRAFT,
            AppointmentBatch.Status.CONFIGURING,
        }:
            raise AppointmentPopulationError(
                "APPOINTMENT_POPULATION_BATCH_FROZEN",
                f"batch status {batch.status} cannot create a new population snapshot",
            )
        clock = as_of_date or timezone.localdate()
        if not isinstance(clock, date):
            raise AppointmentPopulationError(
                "APPOINTMENT_POPULATION_ASOF_INVALID", "as_of_date must be a date"
            )

        relationships = self._active_relationship_rows(clock)
        if not relationships:
            raise AppointmentPopulationError(
                "APPOINTMENT_POPULATION_EMPTY",
                "no active HR03 employment relationships exist at the requested as-of date",
            )

        members = {}
        relationship_owner = {}
        relationship_ids = []
        for row in relationships:
            person_id = str(row["staff_id__person_id_id"])
            relationship_id = str(row["id"])
            relationship_ids.append(row["id"])
            relationship_owner[relationship_id] = person_id
            member = members.setdefault(
                person_id,
                {
                    "personId": person_id,
                    "staffId": str(row["staff_id_id"]),
                    "staffCategoryCode": str(row["staff_id__staff_category_code"] or ""),
                    "employmentRelationships": [],
                    "primaryAssignments": [],
                },
            )
            if member["staffId"] != str(row["staff_id_id"]):
                raise AppointmentPopulationError(
                    "APPOINTMENT_POPULATION_STAFF_AMBIGUOUS",
                    "one person resolves to multiple canonical HR03 staff masters inside tenant",
                )
            member["employmentRelationships"].append(
                {
                    "id": relationship_id,
                    "version": int(row["version"]),
                    "relationshipType": str(row["relationship_type"] or ""),
                    "employmentType": str(row["employment_type"] or ""),
                    "effectiveFrom": row["effective_from"].isoformat(),
                    "effectiveTo": row["effective_to"].isoformat() if row["effective_to"] else None,
                }
            )

        assignments = self._active_primary_assignment_rows(relationship_ids, clock)
        for row in assignments:
            owner = relationship_owner.get(str(row["employment_relationship_id_id"]))
            if owner is None:
                raise AppointmentPopulationError(
                    "APPOINTMENT_POPULATION_ASSIGNMENT_ORPHAN",
                    "active HR03 primary assignment is outside frozen active relationships",
                )
            members[owner]["primaryAssignments"].append(
                {
                    "id": str(row["id"]),
                    "version": int(row["version"]),
                    "employmentRelationshipId": str(row["employment_relationship_id_id"]),
                    "organizationId": row["organization_id_id"],
                    "positionId": row["position_id_id"],
                    "postCatalogId": row["post_catalog_id_id"],
                    "assignmentRoleCode": str(row["assignment_role_code"] or ""),
                    "effectiveFrom": row["effective_from"].isoformat(),
                    "effectiveTo": row["effective_to"].isoformat() if row["effective_to"] else None,
                }
            )

        snapshot_hasher = hashlib.sha256()
        frozen_members = []
        for person_id in sorted(members):
            payload = members[person_id]
            member_hash = self._hash_payload(payload)
            snapshot_hasher.update(f"{person_id}:{member_hash}\n".encode("utf-8"))
            frozen_members.append((payload, member_hash))

        snapshot = AppointmentPopulationSnapshot.objects.create(
            tenant_id=self.tenant_id,
            batch=batch,
            as_of_date=clock,
            snapshot_at=timezone.now(),
            source_domain="HR03",
            source_version=self.SOURCE_VERSION,
            criteria_json={
                "employmentRelationship": {
                    "status": RelationshipStatus.ACTIVE,
                    "effectiveAt": clock.isoformat(),
                },
                "primaryAssignment": {
                    "status": AssignmentStatus.ACTIVE,
                    "assignmentType": AssignmentType.PRIMARY,
                    "evidenceOnly": True,
                },
                "membershipSemantics": "ACTIVE_EMPLOYMENT_RELATIONSHIP",
            },
            member_count=len(frozen_members),
            content_hash=snapshot_hasher.hexdigest(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        AppointmentPopulationMemberSnapshot.objects.bulk_create(
            [
                AppointmentPopulationMemberSnapshot(
                    tenant_id=self.tenant_id,
                    snapshot=snapshot,
                    person_id=payload["personId"],
                    staff_id=payload["staffId"],
                    staff_category_code=payload["staffCategoryCode"],
                    employment_relationship_refs_json=payload["employmentRelationships"],
                    primary_assignment_refs_json=payload["primaryAssignments"],
                    member_hash=member_hash,
                    created_by=self.actor_user_id,
                    updated_by=self.actor_user_id,
                )
                for payload, member_hash in frozen_members
            ],
            batch_size=1000,
        )
        return snapshot

    def require_member(self, *, batch: AppointmentBatch, person_id):
        snapshot = AppointmentPopulationSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            batch=batch,
        ).first()
        if snapshot is None:
            raise AppointmentPopulationError(
                "APPOINTMENT_POPULATION_REQUIRED",
                "batch has no frozen HR03 population snapshot",
            )
        member = AppointmentPopulationMemberSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            snapshot=snapshot,
            person_id=person_id,
        ).first()
        if member is None:
            raise AppointmentPopulationError(
                "APPOINTMENT_PERSON_NOT_IN_FROZEN_POPULATION",
                "person is outside the batch's frozen HR03 population",
            )
        return member
