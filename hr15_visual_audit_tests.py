"""Real Chromium acceptance for the HR15 payroll V2 workspace."""
from __future__ import annotations
import os,tempfile
from pathlib import Path
from unittest import skipUnless
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client,override_settings

@skipUnless(os.getenv('HR_VISUAL_AUDIT')=='1','visual audit is CI-explicit')
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='renshi-hr15-visual-media-'))
class Hr15VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences=True
    def setUp(self):
        from base.models import Company
        from employee.models import Employee,EmployeeWorkInformation
        User=get_user_model();self.company=Company.objects.create(company='跃科 HR15 视觉验收学校',hq=True,address='长沙市薪酬路 15 号',country='CN',state='Hunan',city='Changsha',zip='410000',icon=SimpleUploadedFile('hr15.png',b'hr15',content_type='image/png'))
        self.user=User.objects.create_superuser(username='hr15-visual-auditor',email='hr15-visual@example.invalid',password='hr15-visual-only-password');self.user.is_new_employee=False;self.user.save(update_fields=['is_new_employee'])
        self.employee=Employee.objects.create(employee_user_id=self.user,employee_first_name='HR15',employee_last_name='视觉验收员',email='hr15-employee@example.invalid',phone='13800000015',is_active=True)
        work,_=EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        if work.company_id_id!=self.company.pk:work.company_id=self.company;work.save(update_fields=['company_id'])
        client=Client();client.force_login(self.user);session=client.session;session['selected_company']=str(self.company.pk);session['otp_code_verified']=True;session.save();self.session_cookie=client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir=Path(os.getenv('HR_VISUAL_ARTIFACT_DIR','artifacts/hr-visual'))/'HR15-V2';self.out_dir.mkdir(parents=True,exist_ok=True)
    def test_capture_hr15_v2_desktop_and_mobile(self):
        try:from playwright.sync_api import sync_playwright
        except ImportError as exc:raise RuntimeError('playwright must be installed for HR visual audit') from exc
        routes=['/hr/payroll/','/hr/payroll/profiles/','/hr/payroll/periods/','/hr/payroll/calculations/','/hr/payroll/rules/','/hr/payroll/allowances/','/hr/payroll/social-security/','/hr/payroll/results/','/hr/payroll/payments/','/hr/payroll/reconciliation/','/hr/payroll/legacy-takeover/']
        page_errors=[];console_errors=[];static_failures=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1);context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.session_cookie,'url':self.live_server_url}]);page=context.new_page();page.on('pageerror',lambda exc:page_errors.append(str(exc)));page.on('console',lambda msg:console_errors.append(msg.text) if msg.type=='error' else None)
                page.on('response',lambda response:static_failures.append(f'{response.status} {response.url}') if '/static/hr/' in response.url and response.status>=400 else None)
                response=page.goto(self.live_server_url+routes[0],wait_until='networkidle');self.assertIsNotNone(response);self.assertEqual(response.status,200);self.assertEqual(page.locator("[data-module='HR15']").count(),1);self.assertEqual(page.locator('.hr15-nav a').count(),11);self.assertEqual(page.locator('.hr15-process__step').count(),6);self.assertEqual(page.locator('.hr15-hero').count(),0);self.assertEqual(page.locator('#hr15-kpis .hr15-kpi').count(),6)
                page.wait_for_function("""() => { const v=document.querySelector('#hr15-kpis .hr15-kpi b'); return v && v.textContent.trim() !== '—'; }""",timeout=8000)
                styles=page.evaluate("""() => Array.from(document.styleSheets).map(s=>s.href||'').filter(Boolean)""");diagnostic=f'styles={styles}; page_errors={page_errors}; console_errors={console_errors}; static_failures={static_failures}';self.assertTrue(any('/hr/css/hr-v2.css' in x for x in styles),diagnostic);self.assertTrue(any('/hr/css/hr15-payroll.css' in x for x in styles),diagnostic);self.assertEqual(page_errors,[],diagnostic);self.assertEqual(static_failures,[],diagnostic);page.screenshot(path=str(self.out_dir/'desktop-overview.png'),full_page=True)
                for route in routes[1:]:
                    response=page.goto(self.live_server_url+route,wait_until='networkidle');self.assertIsNotNone(response);self.assertEqual(response.status,200,f'HR15 {route} returned HTTP {response.status}');self.assertEqual(page.locator("[data-module='HR15']").count(),1)
                    if route.endswith('/legacy-takeover/'):
                        self.assertEqual(page.locator('#hr15live-reconcile').count(),1,'HR15 legacy reconciliation UI lost during V2 migration')
                page.set_viewport_size({'width':390,'height':844});response=page.goto(self.live_server_url+routes[0],wait_until='networkidle');self.assertIsNotNone(response);self.assertEqual(response.status,200);self.assertEqual(page.locator('.hr-v2-mobile-section-switcher').count(),1);page.screenshot(path=str(self.out_dir/'mobile-overview.png'),full_page=True);context.close()
            finally:browser.close()
        self.assertEqual(page_errors,[],'HR15 browser page errors: '+' | '.join(page_errors));self.assertEqual(console_errors,[],'HR15 browser console errors: '+' | '.join(console_errors));self.assertEqual(static_failures,[],'HR15 HR static failures: '+' | '.join(static_failures))
