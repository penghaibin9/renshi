from django.db import migrations, models
import django.db.models.deletion


APPEND_ONLY_TABLES = (
    "hr_time_hrtimebalanceledger",
    "hr_time_hrleaveledgerentry",
    "hr_time_hrcomptimeledger",
    "hr_time_hrtimeclosesnapshot",
    "hr_time_hrpayrolltimebasis",
    "hr_time_hrabsencefact",
)


TRIGGER_NAMES = (
    *(f"{table}_no_update" for table in APPEND_ONLY_TABLES),
    *(f"{table}_no_delete" for table in APPEND_ONLY_TABLES),
    "hr11_raw_event_insert_guard",
    "hr11_raw_event_update_guard",
    "hr11_raw_event_no_delete",
    "hr11_leave_ledger_insert_guard",
    "hr11_time_ledger_insert_guard",
    "hr11_comp_ledger_insert_guard",
    "hr11_close_snapshot_insert_guard",
    "hr11_payroll_basis_insert_guard",
    "hr11_absence_fact_insert_guard",
    "hr11_overtime_fact_insert_guard",
    "hr11_overtime_fact_update_guard",
    "hr11_overtime_fact_no_delete",
    "hr11_day_fact_insert_guard",
    "hr11_day_fact_update_guard",
    "hr11_day_fact_delete_guard",
    "hr11_reopen_batch_insert_guard",
    "hr11_reopen_batch_update_guard",
    "hr11_reopen_batch_no_delete",
    "hr11_close_period_insert_guard",
    "hr11_close_period_update_guard",
    "hr11_time_policy_insert_guard",
    "hr11_time_policy_update_guard",
    "hr11_time_policy_delete_guard",
    "hr11_leave_policy_insert_guard",
    "hr11_leave_policy_update_guard",
    "hr11_leave_policy_delete_guard",
    "hr11_calendar_version_insert_guard",
    "hr11_calendar_version_update_guard",
    "hr11_calendar_version_delete_guard",
    "hr11_calendar_day_insert_guard",
    "hr11_calendar_day_update_guard",
    "hr11_calendar_day_delete_guard",
)


def quarantine_unsealed_overtime(apps, schema_editor):
    Fact = apps.get_model("hr_time", "HrOvertimeFact")
    Fact.objects.filter(verification_status="VERIFIED").filter(
        verification_receipt_hash=""
    ).update(
        verification_status="CANDIDATE",
        settlement_mode="POLICY_DEPENDENT",
        verified_at=None,
        verified_by=None,
    )


def validate_existing_close_periods(apps, schema_editor):
    Period = apps.get_model("hr_time", "HrTimeClosePeriod")
    furthest_by_tenant = {}
    for row in Period.objects.order_by("tenant_id", "start_date", "end_date", "id").iterator():
        previous = furthest_by_tenant.get(row.tenant_id)
        if previous is not None and row.start_date <= previous.end_date:
            raise RuntimeError(
                "HR11_CLOSE_PERIOD_OVERLAP: reconcile tenant "
                f"{row.tenant_id} periods {previous.id}/{row.id} before migration"
            )
        if previous is None or row.end_date > previous.end_date:
            furthest_by_tenant[row.tenant_id] = row


def remove_mysql_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for name in TRIGGER_NAMES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")


def install_mysql_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    remove_mysql_seals(apps, schema_editor)

    for table in APPEND_ONLY_TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'HR11_FORMAL_EVIDENCE_IMMUTABLE'"
        )
        schema_editor.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'HR11_FORMAL_EVIDENCE_APPEND_ONLY'"
        )

    statements = (
        """
        CREATE TRIGGER hr11_raw_event_insert_guard
        BEFORE INSERT ON hr_time_hrrawtimeevent
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrtimeeventsource s
              WHERE s.id = NEW.source_id AND s.tenant_id = NEW.tenant_id
                AND NEW.trust_level BETWEEN 1 AND s.trust_level) <> 1
             OR (NEW.device_id IS NOT NULL AND
                 (SELECT COUNT(*) FROM hr_time_hrattendancedevice d
                  WHERE d.id = NEW.device_id AND d.tenant_id = NEW.tenant_id) <> 1) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_RAW_EVENT_PARENT_TENANT_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_raw_event_update_guard
        BEFORE UPDATE ON hr_time_hrrawtimeevent
        FOR EACH ROW
        BEGIN
          IF NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.staff_master_id <=> NEW.staff_master_id)
             OR NOT (OLD.event_type <=> NEW.event_type)
             OR NOT (OLD.event_at_utc <=> NEW.event_at_utc)
             OR NOT (OLD.event_timezone <=> NEW.event_timezone)
             OR NOT (OLD.local_event_at <=> NEW.local_event_at)
             OR NOT (OLD.source_id <=> NEW.source_id)
             OR NOT (OLD.source_event_id <=> NEW.source_event_id)
             OR NOT (OLD.dedupe_key <=> NEW.dedupe_key)
             OR NOT (OLD.device_id <=> NEW.device_id)
             OR NOT (OLD.location_ref <=> NEW.location_ref)
             OR NOT (OLD.raw_payload_hash <=> NEW.raw_payload_hash)
             OR NOT (OLD.trust_level <=> NEW.trust_level) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_RAW_EVENT_IMMUTABLE';
          END IF;
          IF NOT (
            OLD.ingest_status = NEW.ingest_status
            OR (OLD.ingest_status = 'RECEIVED' AND NEW.ingest_status IN
                ('VALIDATED', 'PERSON_UNMAPPED', 'REJECTED', 'STAGED'))
            OR (OLD.ingest_status = 'STAGED' AND NEW.ingest_status IN
                ('VALIDATED', 'REJECTED'))
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_RAW_EVENT_STATE_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_raw_event_no_delete
        BEFORE DELETE ON hr_time_hrrawtimeevent
        FOR EACH ROW SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR11_RAW_EVENT_APPEND_ONLY'
        """,
        """
        CREATE TRIGGER hr11_leave_ledger_insert_guard
        BEFORE INSERT ON hr_time_hrleaveledgerentry
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrleaveaccount a
              WHERE a.id = NEW.account_id AND a.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_LEDGER_ACCOUNT_TENANT_INVALID';
          END IF;
          IF EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND NEW.effective_date BETWEEN p.start_date AND p.end_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_LEDGER_PERIOD_CLOSED';
          END IF;
          IF NEW.entry_type = 'RESERVATION_RELEASE' THEN
            IF NEW.reversal_of_id IS NULL OR
               (SELECT COUNT(*) FROM hr_time_hrleaveledgerentry r
                WHERE r.id = NEW.reversal_of_id AND r.tenant_id = NEW.tenant_id
                  AND r.account_id = NEW.account_id AND r.entry_type = 'RESERVE'
                  AND r.amount = NEW.amount AND r.unit = NEW.unit) <> 1 THEN
              SIGNAL SQLSTATE '45000'
              SET MESSAGE_TEXT = 'HR11_LEAVE_RESERVATION_RELEASE_INVALID';
            END IF;
          ELSEIF NEW.reversal_of_id IS NOT NULL THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_LEDGER_REVERSAL_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_time_ledger_insert_guard
        BEFORE INSERT ON hr_time_hrtimebalanceledger
        FOR EACH ROW
        BEGIN
          IF EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND NEW.effective_date BETWEEN p.start_date AND p.end_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_LEDGER_PERIOD_CLOSED';
          END IF;
          IF NEW.reversal_of_id IS NOT NULL AND
             (SELECT COUNT(*) FROM hr_time_hrtimebalanceledger r
              WHERE r.id = NEW.reversal_of_id AND r.tenant_id = NEW.tenant_id
                AND r.staff_master_id = NEW.staff_master_id
                AND r.account_type = NEW.account_type) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_LEDGER_REVERSAL_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_comp_ledger_insert_guard
        BEFORE INSERT ON hr_time_hrcomptimeledger
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrcomptimeaccount a
              WHERE a.id = NEW.account_id AND a.tenant_id = NEW.tenant_id) <> 1
             OR (NEW.source_fact_id IS NOT NULL AND
                 (SELECT COUNT(*) FROM hr_time_hrovertimefact f
                  JOIN hr_time_hrcomptimeaccount a ON a.id = NEW.account_id
                  WHERE f.id = NEW.source_fact_id AND f.tenant_id = NEW.tenant_id
                    AND f.staff_master_id = a.staff_master_id
                    AND f.verification_status = 'VERIFIED'
                    AND f.verification_receipt_hash REGEXP '^[0-9a-f]{64}$') <> 1)
             OR (NEW.reversal_of_id IS NOT NULL AND
                 (SELECT COUNT(*) FROM hr_time_hrcomptimeledger r
                  WHERE r.id = NEW.reversal_of_id AND r.tenant_id = NEW.tenant_id
                    AND r.account_id = NEW.account_id) <> 1) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_COMP_TIME_LEDGER_PARENT_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_close_snapshot_insert_guard
        BEFORE INSERT ON hr_time_hrtimeclosesnapshot
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrtimecloseperiod p
              WHERE p.id = NEW.period_id AND p.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_SNAPSHOT_PARENT_TENANT_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_payroll_basis_insert_guard
        BEFORE INSERT ON hr_time_hrpayrolltimebasis
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrtimeclosesnapshot s
              JOIN hr_time_hrtimecloseperiod p ON p.id = s.period_id
              WHERE s.id = NEW.close_snapshot_id AND s.tenant_id = NEW.tenant_id
                AND p.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_PAYROLL_BASIS_PARENT_TENANT_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_absence_fact_insert_guard
        BEFORE INSERT ON hr_time_hrabsencefact
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrleaverequest r
              WHERE r.id = NEW.leave_request_id AND r.tenant_id = NEW.tenant_id
                AND r.staff_master_id = NEW.staff_master_id
                AND r.status = 'APPROVED') <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_ABSENCE_FACT_APPROVAL_INVALID';
          END IF;
          IF EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND NEW.start_at <= p.end_date AND NEW.end_at >= p.start_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_ABSENCE_FACT_PERIOD_CLOSED';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_overtime_fact_insert_guard
        BEFORE INSERT ON hr_time_hrovertimefact
        FOR EACH ROW
        BEGIN
          IF NEW.request_id IS NOT NULL AND
             (SELECT COUNT(*) FROM hr_time_hrovertimerequest r
              WHERE r.id = NEW.request_id AND r.tenant_id = NEW.tenant_id
                AND r.staff_master_id = NEW.staff_master_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_FACT_PARENT_TENANT_INVALID';
          END IF;
          IF NEW.verification_status = 'VERIFIED' AND (
             NEW.settlement_mode = 'POLICY_DEPENDENT'
             OR NEW.verified_at IS NULL OR NEW.verified_by_id IS NULL
             OR NEW.verification_receipt_hash NOT REGEXP '^[0-9a-f]{64}$'
             OR JSON_UNQUOTE(JSON_EXTRACT(NEW.verification_receipt_json, '$.providerCode'))
                <> 'HR11_OVERTIME_VERIFICATION_V1'
             OR COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                  NEW.verification_receipt_json, '$.idempotencyKey')), '') = '') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_VERIFICATION_UNTRUSTED';
          END IF;
          IF NEW.verification_status = 'VERIFIED' AND EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND DATE(NEW.actual_start_at) <= p.end_date
                AND DATE(NEW.actual_end_at) >= p.start_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_PERIOD_CLOSED';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_overtime_fact_update_guard
        BEFORE UPDATE ON hr_time_hrovertimefact
        FOR EACH ROW
        BEGIN
          IF OLD.verification_status IN ('VERIFIED', 'REJECTED') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_FACT_IMMUTABLE';
          END IF;
          IF NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.request_id <=> NEW.request_id)
             OR NOT (OLD.staff_master_id <=> NEW.staff_master_id)
             OR NOT (OLD.actual_start_at <=> NEW.actual_start_at)
             OR NOT (OLD.actual_end_at <=> NEW.actual_end_at)
             OR NOT (OLD.actual_minutes <=> NEW.actual_minutes)
             OR NOT (OLD.eligible_minutes <=> NEW.eligible_minutes)
             OR NOT (OLD.policy_version_id <=> NEW.policy_version_id) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_FACT_IDENTITY_IMMUTABLE';
          END IF;
          IF NEW.verification_status = 'VERIFIED' AND (
             OLD.verification_status <> 'CANDIDATE'
             OR NEW.settlement_mode = 'POLICY_DEPENDENT'
             OR NEW.verified_at IS NULL OR NEW.verified_by_id IS NULL
             OR NEW.verification_receipt_hash NOT REGEXP '^[0-9a-f]{64}$'
             OR JSON_UNQUOTE(JSON_EXTRACT(NEW.verification_receipt_json, '$.providerCode'))
                <> 'HR11_OVERTIME_VERIFICATION_V1'
             OR COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                  NEW.verification_receipt_json, '$.idempotencyKey')), '') = '') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_VERIFICATION_UNTRUSTED';
          END IF;
          IF NEW.verification_status = 'VERIFIED' AND EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND DATE(NEW.actual_start_at) <= p.end_date
                AND DATE(NEW.actual_end_at) >= p.start_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_PERIOD_CLOSED';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_overtime_fact_no_delete
        BEFORE DELETE ON hr_time_hrovertimefact
        FOR EACH ROW
        BEGIN
          IF OLD.verification_status IN ('VERIFIED', 'REJECTED') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_OVERTIME_FACT_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_day_fact_insert_guard
        BEFORE INSERT ON hr_time_hrattendancedayfact
        FOR EACH ROW
        BEGIN
          IF NEW.finalized = 1 AND
             (SELECT COUNT(*) FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status = 'CLOSED'
                AND p.snapshot_id IS NOT NULL
                AND NEW.business_date BETWEEN p.start_date AND p.end_date) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_DAY_FACT_FINALIZE_REQUIRES_CLOSED_PERIOD';
          END IF;
          IF NEW.finalized = 0 AND EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND NEW.business_date BETWEEN p.start_date AND p.end_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_DAY_FACT_PERIOD_CLOSED';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_day_fact_update_guard
        BEFORE UPDATE ON hr_time_hrattendancedayfact
        FOR EACH ROW
        BEGIN
          IF OLD.finalized = 1 AND (
             NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.staff_master_id <=> NEW.staff_master_id)
             OR NOT (OLD.assignment_id <=> NEW.assignment_id)
             OR NOT (OLD.business_date <=> NEW.business_date)
             OR NOT (OLD.policy_version_id <=> NEW.policy_version_id)
             OR NOT (OLD.calendar_version_id <=> NEW.calendar_version_id)
             OR NOT (OLD.schedule_snapshot_json <=> NEW.schedule_snapshot_json)
             OR NOT (OLD.expected_minutes <=> NEW.expected_minutes)
             OR NOT (OLD.actual_minutes <=> NEW.actual_minutes)
             OR NOT (OLD.credited_minutes <=> NEW.credited_minutes)
             OR NOT (OLD.authorized_absence_minutes <=> NEW.authorized_absence_minutes)
             OR NOT (OLD.overtime_minutes_candidate <=> NEW.overtime_minutes_candidate)
             OR NOT (OLD.status <=> NEW.status)
             OR NOT (OLD.evaluation_version <=> NEW.evaluation_version)
             OR NOT (OLD.source_pair_ids <=> NEW.source_pair_ids)
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_FINALIZED_DAY_FACT_IMMUTABLE';
          END IF;
          IF OLD.finalized = 0 AND NEW.finalized = 1 AND
             (SELECT COUNT(*) FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status = 'CLOSED'
                AND p.snapshot_id IS NOT NULL
                AND NEW.business_date BETWEEN p.start_date AND p.end_date) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_DAY_FACT_FINALIZE_REQUIRES_CLOSED_PERIOD';
          END IF;
          IF OLD.finalized = 0 AND NEW.finalized = 0 AND EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status IN ('PRE_CLOSE', 'CLOSED')
                AND NEW.business_date BETWEEN p.start_date AND p.end_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_DAY_FACT_PERIOD_CLOSED';
          END IF;
          IF OLD.finalized = 1 AND NEW.finalized = 0 AND
             (SELECT COUNT(*) FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id AND p.status = 'REOPENED'
                AND NEW.business_date BETWEEN p.start_date AND p.end_date
                AND EXISTS (
                  SELECT 1 FROM hr_time_hrtimecorrectionbatch b
                  WHERE b.period_id = p.id AND b.tenant_id = p.tenant_id
                    AND b.status = 'APPROVED'
                )) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_DAY_FACT_UNFREEZE_REQUIRES_APPROVED_REOPEN';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_day_fact_delete_guard
        BEFORE DELETE ON hr_time_hrattendancedayfact
        FOR EACH ROW
        BEGIN
          IF OLD.finalized = 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_FINALIZED_DAY_FACT_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_reopen_batch_insert_guard
        BEFORE INSERT ON hr_time_hrtimecorrectionbatch
        FOR EACH ROW
        BEGIN
          IF NEW.status <> 'REQUESTED' OR NEW.requested_by_id IS NULL
             OR NEW.approved_by_id IS NOT NULL OR NEW.approved_at IS NOT NULL
             OR (SELECT COUNT(*) FROM hr_time_hrtimecloseperiod p
                 WHERE p.id = NEW.period_id AND p.tenant_id = NEW.tenant_id
                   AND p.status = 'CLOSED'
                   AND p.snapshot_id = NEW.before_snapshot_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_REOPEN_REQUEST_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_reopen_batch_update_guard
        BEFORE UPDATE ON hr_time_hrtimecorrectionbatch
        FOR EACH ROW
        BEGIN
          IF NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.period_id <=> NEW.period_id)
             OR NOT (OLD.reason <=> NEW.reason)
             OR NOT (OLD.request_key <=> NEW.request_key)
             OR NOT (OLD.requested_by_id <=> NEW.requested_by_id)
             OR NOT (OLD.before_snapshot_id <=> NEW.before_snapshot_id) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_REOPEN_REQUEST_IDENTITY_IMMUTABLE';
          END IF;
          IF NOT (
             (OLD.status = 'REQUESTED' AND NEW.status IN ('APPROVED', 'REJECTED'))
             OR (OLD.status = 'APPROVED' AND NEW.status = 'APPLIED')
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_REOPEN_REQUEST_STATE_INVALID';
          END IF;
          IF NEW.status = 'APPROVED' AND (
             NEW.approved_by_id IS NULL OR NEW.approved_at IS NULL
             OR NEW.approved_by_id = NEW.requested_by_id) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_REOPEN_SEPARATION_OF_DUTY_REQUIRED';
          END IF;
          IF NEW.status = 'APPLIED' AND
             (SELECT COUNT(*) FROM hr_time_hrtimecloseperiod p
              WHERE p.id = NEW.period_id AND p.tenant_id = NEW.tenant_id
                AND p.status = 'CLOSED' AND p.snapshot_id = NEW.after_snapshot_id
                AND NEW.after_snapshot_id <> NEW.before_snapshot_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_RECLOSE_SNAPSHOT_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_reopen_batch_no_delete
        BEFORE DELETE ON hr_time_hrtimecorrectionbatch
        FOR EACH ROW SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR11_REOPEN_REQUEST_APPEND_ONLY'
        """,
        """
        CREATE TRIGGER hr11_close_period_insert_guard
        BEFORE INSERT ON hr_time_hrtimecloseperiod
        FOR EACH ROW
        BEGIN
          IF NEW.status IN ('CLOSED', 'REOPENED') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_PERIOD_INITIAL_STATE_INVALID';
          END IF;
          IF EXISTS (
              SELECT 1 FROM hr_time_hrtimecloseperiod p
              WHERE p.tenant_id = NEW.tenant_id
                AND p.start_date <= NEW.end_date AND p.end_date >= NEW.start_date
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_PERIOD_OVERLAP';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_close_period_update_guard
        BEFORE UPDATE ON hr_time_hrtimecloseperiod
        FOR EACH ROW
        BEGIN
          IF NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.period_type <=> NEW.period_type)
             OR NOT (OLD.start_date <=> NEW.start_date)
             OR NOT (OLD.end_date <=> NEW.end_date) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_PERIOD_IDENTITY_IMMUTABLE';
          END IF;
          IF OLD.status <> NEW.status AND NOT (
             (OLD.status = 'OPEN' AND NEW.status IN ('PRE_CLOSE', 'CLOSED'))
             OR (OLD.status = 'PRE_CLOSE' AND NEW.status IN ('OPEN', 'CLOSED'))
             OR (OLD.status = 'CLOSED' AND NEW.status = 'REOPENED')
             OR (OLD.status = 'REOPENED' AND NEW.status = 'CLOSED')
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_PERIOD_STATE_INVALID';
          END IF;
          IF NEW.status = 'CLOSED' AND (
             NEW.snapshot_id IS NULL
             OR (SELECT COUNT(*) FROM hr_time_hrtimeclosesnapshot s
                 WHERE s.id = NEW.snapshot_id AND s.period_id = NEW.id
                   AND s.tenant_id = NEW.tenant_id) <> 1) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_PERIOD_SNAPSHOT_INVALID';
          END IF;
          IF OLD.status = 'CLOSED' AND NEW.status = 'REOPENED' AND
             (SELECT COUNT(*) FROM hr_time_hrtimecorrectionbatch b
              WHERE b.period_id = NEW.id AND b.tenant_id = NEW.tenant_id
                AND b.status = 'APPROVED') <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CLOSE_PERIOD_REOPEN_APPROVAL_REQUIRED';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_time_policy_insert_guard
        BEFORE INSERT ON hr_time_hrtimepolicyversion
        FOR EACH ROW
        BEGIN
          IF NEW.tenant_id IS NOT NULL AND NEW.policy_pack_id IS NOT NULL AND (
             (SELECT COUNT(*) FROM hr_time_hrtimepolicypack p
              WHERE p.id = NEW.policy_pack_id AND p.tenant_id = NEW.tenant_id) <> 1
             OR (NEW.recording_profile_id IS NOT NULL AND
                 (SELECT COUNT(*) FROM hr_time_hrtimerecordingprofile r
                  WHERE r.id = NEW.recording_profile_id
                    AND r.tenant_id = NEW.tenant_id) <> 1)) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_POLICY_PARENT_TENANT_INVALID';
          END IF;
          IF NEW.status = 'PUBLISHED' AND (
             NEW.published_at IS NULL
             OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_POLICY_PUBLISH_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_time_policy_update_guard
        BEFORE UPDATE ON hr_time_hrtimepolicyversion
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrtimepolicypack p
              WHERE p.id = NEW.policy_pack_id AND p.tenant_id = NEW.tenant_id) <> 1
             OR (NEW.recording_profile_id IS NOT NULL AND
                 (SELECT COUNT(*) FROM hr_time_hrtimerecordingprofile r
                  WHERE r.id = NEW.recording_profile_id
                    AND r.tenant_id = NEW.tenant_id) <> 1) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_POLICY_PARENT_TENANT_INVALID';
          END IF;
          IF OLD.status <> 'PUBLISHED' AND NEW.status = 'PUBLISHED' AND (
             NEW.published_at IS NULL
             OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_POLICY_PUBLISH_INVALID';
          END IF;
          IF OLD.status = 'RETIRED' OR (OLD.status = 'PUBLISHED' AND (
             NEW.status NOT IN ('PUBLISHED', 'RETIRED')
             OR NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.policy_pack_id <=> NEW.policy_pack_id)
             OR NOT (OLD.version_no <=> NEW.version_no)
             OR NOT (OLD.recording_profile_id <=> NEW.recording_profile_id)
             OR NOT (OLD.work_calendar_policy <=> NEW.work_calendar_policy)
             OR NOT (OLD.schedule_policy <=> NEW.schedule_policy)
             OR NOT (OLD.grace_policy_json <=> NEW.grace_policy_json)
             OR NOT (OLD.rounding_policy_json <=> NEW.rounding_policy_json)
             OR NOT (OLD.overtime_policy_ref <=> NEW.overtime_policy_ref)
             OR NOT (OLD.leave_policy_ref <=> NEW.leave_policy_ref)
             OR NOT (OLD.missing_punch_policy <=> NEW.missing_punch_policy)
             OR NOT (OLD.absence_policy <=> NEW.absence_policy)
             OR NOT (OLD.effective_from <=> NEW.effective_from)
             OR NOT (OLD.effective_to <=> NEW.effective_to)
             OR NOT (OLD.published_at <=> NEW.published_at)
             OR NOT (OLD.published_by_id <=> NEW.published_by_id)
             OR NOT (OLD.content_hash <=> NEW.content_hash)
          )) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_POLICY_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_time_policy_delete_guard
        BEFORE DELETE ON hr_time_hrtimepolicyversion
        FOR EACH ROW
        BEGIN
          IF OLD.status <> 'DRAFT' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_TIME_POLICY_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_leave_policy_insert_guard
        BEFORE INSERT ON hr_time_hrleavepolicyversion
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrleavepolicypack p
              WHERE p.id = NEW.leave_policy_pack_id AND p.tenant_id = NEW.tenant_id) <> 1
             OR (SELECT COUNT(*) FROM hr_time_hrleavetype t
                 WHERE t.id = NEW.leave_type_id AND t.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_POLICY_PARENT_TENANT_INVALID';
          END IF;
          IF NEW.status = 'PUBLISHED' AND (
             NEW.published_at IS NULL
             OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_POLICY_PUBLISH_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_leave_policy_update_guard
        BEFORE UPDATE ON hr_time_hrleavepolicyversion
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrleavepolicypack p
              WHERE p.id = NEW.leave_policy_pack_id AND p.tenant_id = NEW.tenant_id) <> 1
             OR (SELECT COUNT(*) FROM hr_time_hrleavetype t
                 WHERE t.id = NEW.leave_type_id AND t.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_POLICY_PARENT_TENANT_INVALID';
          END IF;
          IF OLD.status <> 'PUBLISHED' AND NEW.status = 'PUBLISHED' AND (
             NEW.published_at IS NULL
             OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_POLICY_PUBLISH_INVALID';
          END IF;
          IF OLD.status = 'RETIRED' OR (OLD.status = 'PUBLISHED' AND (
             NEW.status NOT IN ('PUBLISHED', 'RETIRED')
             OR NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.leave_policy_pack_id <=> NEW.leave_policy_pack_id)
             OR NOT (OLD.leave_type_id <=> NEW.leave_type_id)
             OR NOT (OLD.version_no <=> NEW.version_no)
             OR NOT (OLD.entitlement_mode <=> NEW.entitlement_mode)
             OR NOT (OLD.eligibility_rule <=> NEW.eligibility_rule)
             OR NOT (OLD.grant_accrual_rule <=> NEW.grant_accrual_rule)
             OR NOT (OLD.carry_forward_rule <=> NEW.carry_forward_rule)
             OR NOT (OLD.expiry_rule <=> NEW.expiry_rule)
             OR NOT (OLD.reservation_rule <=> NEW.reservation_rule)
             OR NOT (OLD.evidence_rule <=> NEW.evidence_rule)
             OR NOT (OLD.approval_rule <=> NEW.approval_rule)
             OR NOT (OLD.interaction_rules <=> NEW.interaction_rules)
             OR NOT (OLD.effective_from <=> NEW.effective_from)
             OR NOT (OLD.effective_to <=> NEW.effective_to)
             OR NOT (OLD.published_at <=> NEW.published_at)
             OR NOT (OLD.published_by_id <=> NEW.published_by_id)
             OR NOT (OLD.content_hash <=> NEW.content_hash)
          )) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_POLICY_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_leave_policy_delete_guard
        BEFORE DELETE ON hr_time_hrleavepolicyversion
        FOR EACH ROW
        BEGIN
          IF OLD.status <> 'DRAFT' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_LEAVE_POLICY_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_calendar_version_insert_guard
        BEFORE INSERT ON hr_time_hrworkcalendarversion
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrworkcalendar c
              WHERE c.id = NEW.calendar_id AND c.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_VERSION_PARENT_TENANT_INVALID';
          END IF;
          IF NEW.status = 'PUBLISHED' AND (
             NEW.published_at IS NULL
             OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_VERSION_PUBLISH_INVALID';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_calendar_version_update_guard
        BEFORE UPDATE ON hr_time_hrworkcalendarversion
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrworkcalendar c
              WHERE c.id = NEW.calendar_id AND c.tenant_id = NEW.tenant_id) <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_VERSION_PARENT_TENANT_INVALID';
          END IF;
          IF OLD.status <> 'PUBLISHED' AND NEW.status = 'PUBLISHED' AND (
             NEW.published_at IS NULL
             OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_VERSION_PUBLISH_INVALID';
          END IF;
          IF OLD.status = 'SUPERSEDED' OR (OLD.status = 'PUBLISHED' AND (
             NEW.status NOT IN ('PUBLISHED', 'SUPERSEDED')
             OR NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.calendar_id <=> NEW.calendar_id)
             OR NOT (OLD.year <=> NEW.year)
             OR NOT (OLD.version_no <=> NEW.version_no)
             OR NOT (OLD.source_type <=> NEW.source_type)
             OR NOT (OLD.source_ref <=> NEW.source_ref)
             OR NOT (OLD.published_at <=> NEW.published_at)
             OR NOT (OLD.published_by_id <=> NEW.published_by_id)
             OR NOT (OLD.content_hash <=> NEW.content_hash)
             OR NOT (OLD.supersedes_version_id <=> NEW.supersedes_version_id)
          )) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_VERSION_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_calendar_version_delete_guard
        BEFORE DELETE ON hr_time_hrworkcalendarversion
        FOR EACH ROW
        BEGIN
          IF OLD.status <> 'DRAFT' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_VERSION_IMMUTABLE';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_calendar_day_insert_guard
        BEFORE INSERT ON hr_time_hrcalendarday
        FOR EACH ROW
        BEGIN
          IF (SELECT COUNT(*) FROM hr_time_hrworkcalendarversion v
              WHERE v.id = NEW.calendar_version_id AND v.tenant_id = NEW.tenant_id
                AND v.status = 'DRAFT') <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_DAY_VERSION_FROZEN';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_calendar_day_update_guard
        BEFORE UPDATE ON hr_time_hrcalendarday
        FOR EACH ROW
        BEGIN
          IF (SELECT status FROM hr_time_hrworkcalendarversion
              WHERE id = OLD.calendar_version_id) <> 'DRAFT'
             OR NOT (OLD.tenant_id <=> NEW.tenant_id)
             OR NOT (OLD.calendar_version_id <=> NEW.calendar_version_id) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_DAY_VERSION_FROZEN';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr11_calendar_day_delete_guard
        BEFORE DELETE ON hr_time_hrcalendarday
        FOR EACH ROW
        BEGIN
          IF (SELECT status FROM hr_time_hrworkcalendarversion
              WHERE id = OLD.calendar_version_id) <> 'DRAFT' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR11_CALENDAR_DAY_VERSION_FROZEN';
          END IF;
        END
        """,
    )
    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_time", "0013_alter_hrtimepermissionmeta_options")]

    operations = [
        migrations.AddField(
            model_name="hrovertimefact",
            name="verification_receipt_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hrovertimefact",
            name="verification_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="hrovertimefact",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hrovertimefact",
            name="verified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="horilla_auth.horillauser",
            ),
        ),
        migrations.AlterField(
            model_name="hrleaveledgerentry",
            name="reversal_of",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversals",
                to="hr_time.hrleaveledgerentry",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrabsencefact",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "leave_request", "fact_version"),
                name="uniq_hr11_absence_fact_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrcomptimeledger",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "source_fact", "entry_type"),
                name="uniq_hr11_comp_fact_entry",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrleaveledgerentry",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "reversal_of"),
                name="uniq_hr11_leave_reversal",
            ),
        ),
        migrations.RunPython(quarantine_unsealed_overtime, migrations.RunPython.noop),
        migrations.RunPython(validate_existing_close_periods, migrations.RunPython.noop),
        migrations.RunPython(
            install_mysql_seals,
            remove_mysql_seals,
            atomic=False,
        ),
    ]
