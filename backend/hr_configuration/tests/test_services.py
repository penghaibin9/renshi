from django.test import TestCase

from hr_configuration.forms import StageForm
from hr_configuration.models import FieldDefinition, FormDefinition, WorkflowStage, WorkflowVersion
from hr_configuration.services import clone_to_draft, create_workflow, get_published_workflow_config, publish


class ConfigurationServiceTests(TestCase):
    def _draft(self):
        workflow,version=create_workflow(tenant_id=7,actor_user_id=11,code="TEST_FLOW",name="测试流程",business_domain="HR05")
        WorkflowStage.objects.create(tenant_id=7,version=version,code="START",name="开始",sort_order=10,is_start=True,created_by=11)
        WorkflowStage.objects.create(tenant_id=7,version=version,code="DONE",name="完成",sort_order=20,is_end=True,created_by=11)
        form=FormDefinition.objects.create(tenant_id=7,version=version,code="MAIN",title="主表",stage_code="START",sort_order=10,created_by=11)
        FieldDefinition.objects.create(tenant_id=7,version=version,form=form,key="STAFF_NO",label="工号",sort_order=10,required=True,created_by=11)
        return workflow,version

    def test_publish_freezes_version_and_returns_stable_contract(self):
        workflow,version=self._draft()
        published=publish(version_id=version.id,tenant_id=7,actor_user_id=11)
        self.assertEqual(len(published.content_hash),64)
        payload=get_published_workflow_config(tenant_id=7,business_domain="HR05",workflow_code="TEST_FLOW")
        self.assertEqual(payload["workflow"]["code"],"TEST_FLOW")
        self.assertEqual(payload["fields"][0]["formCode"],"MAIN")
        stage=WorkflowStage.objects.get(version=published,code="START");stage.name="被篡改"
        with self.assertRaises(ValueError):stage.save()

    def test_clone_creates_new_editable_draft(self):
        workflow,version=self._draft();publish(version_id=version.id,tenant_id=7,actor_user_id=11)
        draft=clone_to_draft(workflow_id=workflow.id,tenant_id=7,actor_user_id=12)
        self.assertEqual(draft.version_no,2)
        self.assertEqual(FieldDefinition.objects.filter(version=draft).count(),1)

    def test_published_version_rejects_queryset_and_bulk_mutation(self):
        workflow,version=self._draft();published=publish(version_id=version.id,tenant_id=7,actor_user_id=11)
        with self.assertRaises(ValueError):
            WorkflowStage.objects.filter(version=published).update(name="批量篡改")
        published.change_note="批量篡改"
        with self.assertRaises(ValueError):
            WorkflowVersion.objects.bulk_update([published],["change_note"])
        published.version_no=99
        with self.assertRaises(ValueError):
            published.save()

    def test_model_form_is_tenant_bound_before_model_validation(self):
        _,version=create_workflow(tenant_id=77,actor_user_id=11,code="FORM_FLOW",name="表单流程",business_domain="HR05")
        form=StageForm(data={"code":"START","name":"开始","sort_order":10,"is_start":"on","is_end":""},version=version,prefix="stage")
        # Prefix-aware browser payload mirrors the workflow detail UI.
        form=StageForm(data={"stage-code":"START","stage-name":"开始","stage-sort_order":10,"stage-is_start":"on"},version=version,prefix="stage")
        self.assertTrue(form.is_valid(),form.errors)
