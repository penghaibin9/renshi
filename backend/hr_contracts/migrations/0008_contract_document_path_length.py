from django.db import migrations, models
from django.db.models.functions import Length


def reject_oversized_document_paths(apps, schema_editor):
    document_model = apps.get_model("hr_contracts", "HrAgreementDocument")
    oversized = (
        document_model.objects.annotate(path_length=Length("file_path"))
        .filter(path_length__gt=255)
        .order_by("id")
        .values_list("id", "path_length")
        .first()
    )
    if oversized is not None:
        document_id, path_length = oversized
        raise RuntimeError(
            "HR07 contract document path exceeds 255 characters: "
            f"document={document_id} length={path_length}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("hr_contracts", "0007_contract_document_security"),
    ]

    operations = [
        migrations.RunPython(
            reject_oversized_document_paths,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="hragreementdocument",
            name="file_path",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
