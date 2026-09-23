#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

root = Path(os.environ["SNAPSHOT_ROOT"])
old = "hr_dev_fact_uuid_type_valid_idx"
new = "hr_dev_fact_uuid_type_val_idx"
assert len(old) == 31
assert len(new) <= 30

model = root / "backend/hr10_development/models/development_fact.py"
text = model.read_text(encoding="utf-8")
assert text.count(old) == 1, "unexpected HR10 model index occurrence count"
model.write_text(text.replace(old, new), encoding="utf-8")

migration = root / "backend/hr10_development/migrations/0029_shorten_fact_uuid_index_name.py"
assert not migration.exists(), "0029 migration unexpectedly already exists"
migration.write_text(
    '''from django.db import migrations\n\n\nclass Migration(migrations.Migration):\n    dependencies = [("hr10_development", "0028_hr10_staff_identity_guards")]\n\n    operations = [\n        migrations.RenameIndex(\n            model_name="hrdevelopmentfact",\n            old_name="hr_dev_fact_uuid_type_valid_idx",\n            new_name="hr_dev_fact_uuid_type_val_idx",\n        ),\n    ]\n''',
    encoding="utf-8",
)

contract = root / "scripts/check_hr10_staff_identity_contract.py"
text = contract.read_text(encoding="utf-8")
needle = '    "m28": "backend/hr10_development/migrations/0028_hr10_staff_identity_guards.py",\n'
assert needle in text
text = text.replace(
    needle,
    needle + '    "m29": "backend/hr10_development/migrations/0029_shorten_fact_uuid_index_name.py",\n',
)
old_block = '''    all_in(src["fact"], 'name="hr_dev_fact_uuid_type_valid_idx"')\n    and all_in(src["m28"], "FACT_UUID_INDEX = \\"hr_dev_fact_uuid_type_valid_idx\\""),\n    "model state and retry-safe DB migration use the same canonical fact index name",\n'''
new_block = '''    all_in(src["fact"], 'name="hr_dev_fact_uuid_type_val_idx"')\n    and all_in(src["m28"], "FACT_UUID_INDEX = \\"hr_dev_fact_uuid_type_valid_idx\\"")\n    and all_in(src["m29"], 'old_name="hr_dev_fact_uuid_type_valid_idx"', 'new_name="hr_dev_fact_uuid_type_val_idx"'),\n    "current model uses a <=30-char index name and 0029 safely renames the 0028 historical index",\n'''
assert old_block in text, "HR10 contract block drifted"
contract.write_text(text.replace(old_block, new_block), encoding="utf-8")

print("V1.3.1 runner patch applied: HR10 index 31 chars -> 29 chars with forward RenameIndex migration")
