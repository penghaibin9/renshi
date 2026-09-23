"""Trusted deployment worker: verify an authenticated bank proof and post pending tax."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from hr_payroll.services.policy_tax_service import PolicyTaxService
class Command(BaseCommand):
    help="核对银行签名回执补充支付日；不接受手工填写的无签名付款日期"
    def add_arguments(self,p):
        p.add_argument('--tenant',required=True,type=int);p.add_argument('--actor',required=True,type=int)
        p.add_argument('--instruction',required=True);p.add_argument('--verified-provider-payload',required=True)
    def handle(self,*args,**o):
        path=Path(o['verified_provider_payload'])
        if not path.is_file() or path.stat().st_size>1024*1024:raise CommandError('需要不超过1 MiB的银行原始回执文件')
        try:
            payload=json.loads(path.read_text('utf-8'))
            result=PolicyTaxService(o['tenant'],o['actor']).supplement_verified_date(instruction_id=o['instruction'],provider_payload=payload)
        except Exception as e:raise CommandError(f'未入账：{getattr(e,"code",type(e).__name__)}；请核对可信回执及适配器') from e
        self.stdout.write(json.dumps({'reservationId':str(result.id),'status':result.status}))
