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



# The production lock intentionally includes ldap3. The old unit test expected
# the reviewed client to be absent, which is no longer true. Keep the fail-closed
# assertion but align it with the installed production client: an unreachable
# LDAP provider must fail as LDAP_BIND_FAILED rather than pretending the client
# package is missing.
ldap_test = root / "backend/hr_integration/tests/test_sso_runtime.py"
ldap_text = ldap_test.read_text(encoding="utf-8")
old_expectation = 'self.assertIn(ctx.exception.code,{"LDAP_CLIENT_MISSING","SSO_CREDENTIAL_DECRYPT_FAILED"})'
new_expectation = 'self.assertIn(ctx.exception.code,{"LDAP_BIND_FAILED","SSO_CREDENTIAL_DECRYPT_FAILED"})'
assert old_expectation in ldap_text, "LDAP test contract drifted"
ldap_test.write_text(ldap_text.replace(old_expectation, new_expectation), encoding="utf-8")



# Browser acceptance wording drift: the workflow detail page intentionally
# labels the immutable snapshot as "正式版本", while the older browser script
# required the transient success-message text "已发布". Verify UI semantics
# plus the published API instead of depending on a toast/message string.
browser = root / "scripts/hr_config_integration_browser.py"
browser_text = browser.read_text(encoding="utf-8")
old_publish_assert = '            require("已发布" in page.locator("body").inner_text(), "published state not visible")\n'
new_publish_assert = '            publish_body = page.locator("body").inner_text()\n            require("正式版本" in publish_body and "未发布" not in publish_body, "published formal-version state not visible")\n'
assert old_publish_assert in browser_text, "configuration browser publish assertion drifted"
browser.write_text(browser_text.replace(old_publish_assert, new_publish_assert), encoding="utf-8")

# Integration Hub form buttons must not depend on HTML's implicit submit
# default. Explicit types make the UI deterministic for browsers, automation
# and accessibility tools.
templates = {
    root / "backend/hr_integration/templates/hr_integration/connection_detail.html": {
        '<button class="hrint-btn is-primary">保存映射方案</button>':
        '<button class="hrint-btn is-primary" type="submit">保存映射方案</button>',
    },
    root / "backend/hr_integration/templates/hr_integration/profile_detail.html": {
        '<button class="hrint-danger-link">删除</button>':
        '<button class="hrint-danger-link" type="submit">删除</button>',
        '<button class="hrint-btn is-primary">保存字段映射</button>':
        '<button class="hrint-btn is-primary" type="submit">保存字段映射</button>',
        '<button class="hrint-btn is-danger">删除映射方案</button>':
        '<button class="hrint-btn is-danger" type="submit">删除映射方案</button>',
    },
}
for path, replacements in templates.items():
    template_text = path.read_text(encoding="utf-8")
    for old_html, new_html in replacements.items():
        assert template_text.count(old_html) == 1, f"template button contract drifted: {path.name} {old_html}"
        template_text = template_text.replace(old_html, new_html)
    path.write_text(template_text, encoding="utf-8")

print("V1.3.1 runner patch applied: HR10 + LDAP + publish semantics + explicit Integration Hub submit buttons")
