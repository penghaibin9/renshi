from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hr10_development", "0021_import_pipeline"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="hr10developmentpermissionmeta",
            options={
                "managed": False,
                "permissions": (
                    ("hr.development.plan.view", "Hr Development Plan View"),
                    ("hr.development.plan.create", "Hr Development Plan Create"),
                    ("hr.development.plan.approve", "Hr Development Plan Approve"),
                    ("hr.development.plan.publish", "Hr Development Plan Publish"),
                    ("hr.development.program.view", "Hr Development Program View"),
                    ("hr.development.program.manage", "Hr Development Program Manage"),
                    ("hr.development.program.publish", "Hr Development Program Publish"),
                    ("hr.development.request.view", "Hr Development Request View"),
                    ("hr.development.request.create", "Hr Development Request Create"),
                    ("hr.development.request.approve", "Hr Development Request Approve"),
                    (
                        "hr.development.request.review_budget",
                        "Hr Development Request Review_Budget",
                    ),
                    ("hr.development.practice.view", "Hr Development Practice View"),
                    ("hr.development.practice.manage", "Hr Development Practice Manage"),
                    ("hr.development.practice.publish", "Hr Development Practice Publish"),
                    ("hr.development.process.record", "Hr Development Process Record"),
                    (
                        "hr.development.completion.verify",
                        "Hr Development Completion Verify",
                    ),
                    (
                        "hr.development.evaluation.manage",
                        "Hr Development Evaluation Manage",
                    ),
                    ("hr.development.output.verify", "Hr Development Output Verify"),
                    ("hr.development.record.view", "Hr Development Record View"),
                    ("hr.development.analytics.read", "Hr Development Analytics Read"),
                    ("hr.development.audit", "Hr Development Audit"),
                    ("hr.development.import.manage", "Hr Development Import Manage"),
                ),
            },
        ),
    ]
