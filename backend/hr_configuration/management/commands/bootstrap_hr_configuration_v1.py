from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from hr_configuration.models import FormDefinition, WorkflowStage
from hr_configuration.services import create_workflow, get_draft


DEFAULTS = {
    "HR04": ("RECRUITMENT_HIRING", "招聘录用流程", ["需求确认", "资格审核", "评议考察", "拟录用", "公示", "完成"]),
    "HR05": ("ONBOARDING", "教职工入职流程", ["待报到", "材料核验", "入职办理", "人员激活", "完成"]),
    "HR06": ("PERSONNEL_CHANGE", "人事异动流程", ["申请", "业务审核", "人事复核", "生效", "完成"]),
    "HR12": ("ASSESSMENT", "年度/聘期考核流程", ["启动", "本人自评", "单位评议", "学校校准", "结果确认"]),
    "HR13": ("TITLE_REVIEW", "职称评审流程", ["申报", "资格审核", "专家评审", "公示", "结果确认"]),
    "HR14": ("APPOINTMENT", "岗位聘任流程", ["申请", "资格审核", "聘任评议", "聘任决定", "生效"]),
    "HR16": ("EXIT_RETIREMENT", "退休与离校流程", ["申请/触发", "审核", "清算", "移交", "归档"]),
    "HR17": ("SELF_SERVICE", "教职工本人申请流程", ["本人申请", "受理", "审核", "正式写回", "完成"]),
}


class Command(BaseCommand):
    help = "Idempotently create V1 draft shells for configurable higher-education HR workflows."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument("--actor", type=int, default=None)

    @transaction.atomic
    def handle(self, *args, **options):
        tenant=options["tenant"]; actor=options["actor"]
        if tenant <= 0: raise CommandError("--tenant must be positive")
        created=0
        from hr_configuration.models import WorkflowDefinition
        for domain,(code,name,stages) in DEFAULTS.items():
            workflow=WorkflowDefinition.objects.filter(tenant_id=tenant,code=code).first()
            if workflow:
                draft=get_draft(workflow)
                if not draft:
                    self.stdout.write(f"skip {domain}/{code}: no draft; published config must be cloned explicitly")
                    continue
            else:
                workflow,draft=create_workflow(tenant_id=tenant,actor_user_id=actor,code=code,name=name,business_domain=domain,description="学校级 V1 配置草稿；上线前由学校确认审批角色、字段与模板。")
                created+=1
            if not WorkflowStage.objects.filter(version=draft).exists():
                for idx,label in enumerate(stages,1):
                    WorkflowStage.objects.create(tenant_id=tenant,version=draft,code=f"STAGE_{idx:02d}",name=label,sort_order=idx*10,is_start=idx==1,is_end=idx==len(stages),created_by=actor,updated_by=actor)
            if not FormDefinition.objects.filter(version=draft).exists():
                FormDefinition.objects.create(tenant_id=tenant,version=draft,code="MAIN_FORM",title=f"{name}主表",stage_code="STAGE_01",sort_order=10,description="按本校制度增加字段；不建议直接复制其他学校字段。",created_by=actor,updated_by=actor)
        self.stdout.write(self.style.SUCCESS(f"V1 bootstrap complete; created workflows={created}"))
