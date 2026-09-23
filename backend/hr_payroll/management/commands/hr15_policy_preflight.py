"""Read-only readiness check; never creates trials, tax entries or wage results."""
import json
from django.core.management.base import BaseCommand,CommandError
from django.db.models import Q
from hr_payroll.models import PayrollProfile
from hr_payroll.services.policy_payroll_service import PolicyPayrollService
from hr_payroll.services.policy_math import PolicyPayrollError

class Command(BaseCommand):
    help='Read-only HR15 policy payroll readiness; requires tenant, authenticated operator identifier and period'
    def add_arguments(self,parser):
        parser.add_argument('--tenant',required=True,type=int)
        parser.add_argument('--actor',required=True,type=int)
        parser.add_argument('--period',required=True)
    def handle(self,*args,**options):
        engine=PolicyPayrollService(options['tenant'],options['actor'])
        try:period=engine._period(options['period'])
        except PolicyPayrollError as e:raise CommandError(f'{e.code}: {e}')
        people=PayrollProfile.objects.filter(tenant_id=options['tenant'],status__in=['ACTIVE','ENDED'],effective_from__lte=period.end_date).filter(Q(effective_to__isnull=True)|Q(effective_to__gt=period.start_date)).values_list('staff_id',flat=True).distinct()
        rows=[]
        for staff in people:
            try:
                data=engine.build_input(period,staff);engine.evaluate(data)
                rows.append({'staffId':str(staff),'status':'READY_FOR_TRIAL'})
            except PolicyPayrollError as e:rows.append({'staffId':str(staff),'status':'BLOCKED','code':e.code,'message':str(e)})
        self.stdout.write(json.dumps({'mode':'READ_ONLY_NO_PAYMENT','periodId':str(period.id),'count':len(rows),'rows':rows},ensure_ascii=False,indent=2))
        if not rows or any(x['status']=='BLOCKED' for x in rows):raise CommandError('PAYROLL_PREFLIGHT_BLOCKED: resolve missing approved facts before a trial')
