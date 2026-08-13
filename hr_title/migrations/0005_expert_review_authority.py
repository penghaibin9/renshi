import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_title", "0004_title_qualification_decision")]

    operations = [
        migrations.AlterModelOptions(
            name="titlepolicyversion",
            options={
                "permissions": [
                    ("hr.title.view", "查看 HR13 职称评审工作区"),
                    ("hr.title.review", "执行 HR13 资格审查"),
                    ("hr.title.panel", "维护 HR13 专家评议与表决"),
                ],
            },
        ),
        migrations.AlterField(
            model_name="titleapplicationcase",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("SUBMITTED", "Submitted"),
                    ("RETURNED", "Returned for correction"),
                    ("ELIGIBLE", "Eligibility passed"),
                    ("REJECTED", "Eligibility rejected"),
                    ("WITHDRAWN", "Withdrawn"),
                    ("UNDER_REVIEW", "Under review"),
                    ("REVIEW_NOT_PASSED", "Review not passed"),
                    ("PROPOSED", "Proposed result"),
                    ("PUBLICITY", "Publicity"),
                    ("EFFECTIVE", "Effective"),
                    ("REVOKED", "Revoked"),
                ],
                db_index=True,
                default="DRAFT",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="TitleReviewRound",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("round_no", models.CharField(max_length=64)),
                ("application_case_id", models.UUIDField(db_index=True)),
                ("attempt_no", models.PositiveIntegerField()),
                ("required_ballots", models.PositiveIntegerField()),
                ("required_pass_votes", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("OPEN", "Open"),
                            ("PASSED", "Passed"),
                            ("NOT_PASSED", "Not passed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        db_index=True,
                        default="OPEN",
                        max_length=16,
                    ),
                ),
                ("opened_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                ("closed_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("closure_snapshot_json", models.JSONField(blank=True, default=dict)),
            ],
            options={"db_table": "hr13_title_review_round"},
        ),
        migrations.CreateModel(
            name="TitleReviewAssignment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("assignment_no", models.CharField(max_length=64)),
                ("review_round_id", models.UUIDField(db_index=True)),
                ("reviewer_staff_id", models.UUIDField()),
                (
                    "reviewer_role",
                    models.CharField(
                        choices=[
                            ("EXPERT", "Expert"),
                            ("COMMITTEE", "Committee member"),
                            ("CHAIR", "Chair"),
                        ],
                        default="EXPERT",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ASSIGNED", "Assigned"),
                            ("ACCEPTED", "Accepted"),
                            ("DECLINED", "Declined"),
                        ],
                        db_index=True,
                        default="ASSIGNED",
                        max_length=16,
                    ),
                ),
                ("conflict_declared", models.BooleanField(db_index=True, default=False)),
                ("conflict_note", models.TextField(blank=True, default="")),
                ("assigned_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_title_review_assignment"},
        ),
        migrations.CreateModel(
            name="TitleReviewBallot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("ballot_no", models.CharField(max_length=64)),
                ("review_round_id", models.UUIDField(db_index=True)),
                ("assignment_id", models.UUIDField()),
                (
                    "recommendation",
                    models.CharField(
                        choices=[("PASS", "Pass"), ("FAIL", "Fail"), ("ABSTAIN", "Abstain")],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("score", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("rationale", models.TextField(blank=True, default="")),
                ("submitted_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "hr13_title_review_ballot"},
        ),
        migrations.AddConstraint(
            model_name="titlereviewround",
            constraint=models.UniqueConstraint(fields=("tenant_id", "round_no"), name="uq_hr13_review_round_no"),
        ),
        migrations.AddConstraint(
            model_name="titlereviewround",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr13_review_case_attempt",
            ),
        ),
        migrations.AddConstraint(
            model_name="titlereviewround",
            constraint=models.CheckConstraint(
                condition=models.Q(("required_ballots__gte", 1)), name="ck_hr13_review_ballots_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="titlereviewround",
            constraint=models.CheckConstraint(
                condition=models.Q(("required_pass_votes__gte", 1), ("required_pass_votes__lte", models.F("required_ballots"))),
                name="ck_hr13_review_pass_threshold",
            ),
        ),
        migrations.AddIndex(
            model_name="titlereviewround",
            index=models.Index(fields=["tenant_id", "application_case_id", "status"], name="idx_hr13_review_case_status"),
        ),
        migrations.AddConstraint(
            model_name="titlereviewassignment",
            constraint=models.UniqueConstraint(fields=("tenant_id", "assignment_no"), name="uq_hr13_review_assignment_no"),
        ),
        migrations.AddConstraint(
            model_name="titlereviewassignment",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "review_round_id", "reviewer_staff_id"),
                name="uq_hr13_review_round_reviewer",
            ),
        ),
        migrations.AddIndex(
            model_name="titlereviewassignment",
            index=models.Index(fields=["tenant_id", "review_round_id", "status"], name="idx_hr13_assignment_round"),
        ),
        migrations.AddConstraint(
            model_name="titlereviewballot",
            constraint=models.UniqueConstraint(fields=("tenant_id", "ballot_no"), name="uq_hr13_review_ballot_no"),
        ),
        migrations.AddConstraint(
            model_name="titlereviewballot",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "review_round_id", "assignment_id"),
                name="uq_hr13_review_round_assignment_ballot",
            ),
        ),
        migrations.AddIndex(
            model_name="titlereviewballot",
            index=models.Index(fields=["tenant_id", "review_round_id", "recommendation"], name="idx_hr13_ballot_round"),
        ),
    ]
