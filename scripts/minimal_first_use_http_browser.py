"""Real Chromium / real template+JS, with explicit simulated API responses.

NOT a Django or MySQL end-to-end test. Every evidence file records this boundary.
"""
from pathlib import Path
import importlib.util
import json
import re
from jinja2 import Environment
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'tests/artifacts/minimal-first-use'
JID='11111111-2222-4333-8444-555555555555'

def expect(condition,message):
    if not condition: raise AssertionError(message)

def main():
    ART.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'backend/hr_staff/templates/hr_staff/staff_list.html').read_text()
    content=source.split('{% block content %}',1)[1].split('{% endblock content %}',1)[0]
    script=source.split('<script>',1)[1].split('</script>',1)[0]
    script=script.replace('{{ request.user.pk }}','7').replace('{{ request.session.selected_company }}','1')
    (ART/'staff-import-extracted.js').write_text(script)
    styles='\n'.join((ROOT/f'frontend/static/hr/css/{name}.css').read_text() for name in ('hr-tokens','hr-components','hr-v2','hr03-staff'))
    banner='<aside style="padding:12px;background:#fff3cd;color:#4c3c12">Chromium 交互验收夹具：使用真实模板与脚本，接口响应为测试数据，不是 MySQL 验收。</aside>'
    staff_html=f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><style>{styles}</style></head><body>{banner}{content}<script>{script}</script></body></html>'
    spec=importlib.util.spec_from_file_location('policy',ROOT/'backend/base/first_use_policy.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    progress=policy.first_use_progress({'scope_ok':True,'school_count':1,'organization_ready':True,'staff_ready':False,'roles_ready':False})
    progress.update(next_url='/hr/staff/',next_help='下载 Excel 模板，填写真实人员，校验后再确认写入。',profile_pending=['学校地址','国家','省份','城市','邮编'],profile_url='#profile')
    for step in progress['steps']:
        step.update(state_label='已读取到记录' if step['state']=='done' else '待办理',help='接口夹具：不代表后台真实数据。',url='/hr/staff/' if step['code']=='staff' else '')
    partial=(ROOT/'backend/base/templates/base/settings/first_use_progress.html').read_text()
    rendered=Environment(autoescape=True).from_string(partial).render(first_use=progress)
    admin_css=(ROOT/'frontend/static/hr/css/hr-admin-center.css').read_text()
    admin_js=(ROOT/'frontend/static/hr/js/core/hr-admin-center.js').read_text()
    memo='<ol class="sysadmin-checklist"><li data-check="staff"><button type="button" aria-label="实施备忘"></button><div><strong>人工备忘，不是启用进度</strong></div></li></ol>'
    admin_html=f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{admin_css}</style></head><body>{banner}<main class="sysadmin-center" data-system-admin-center data-school-scope="1">{rendered}{memo}</main><script>{admin_js}</script></body></html>'
    counters={'commit_posts':0,'status_gets':0,'uploads':0}
    state={'dialog':'dismiss','committed':False}
    preview=dict(jobId=JID,status='READY_TO_COMMIT',totalRows=2,validRows=1,failedRows=1,issues=[{'rowNo':3,'field':'department_name','error':'本校未找到部门 <img src=x onerror=alert(1)>'}])
    completed=dict(jobId=JID,status='PARTIAL_FAILED',committed=1,failed=1,total=2,readbackCount=1,readbackComplete=True,legacyUnverifiedRows=0,totalRows=2,validRows=1,failedRows=1,issues=preview['issues'])
    checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
        context=browser.new_context(viewport={'width':1440,'height':1100},accept_downloads=True)
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('dialog',lambda dialog:dialog.accept() if state['dialog']=='accept' else dialog.dismiss())
        def route_handler(route):
            url=route.request.url;method=route.request.method
            if url.endswith('/first-use'):
                route.fulfill(content_type='text/html',body=admin_html)
            elif url.endswith('/staff-page'):
                route.fulfill(content_type='text/html',body=staff_html)
            elif url.endswith('/import/template'):
                route.fulfill(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',body=(ROOT/'backend/hr_staff/resources/staff_import_template.xlsx').read_bytes())
            elif url.endswith('/errors'):
                route.fulfill(content_type='text/csv;charset=utf-8',body='\ufeff原文件行号,字段,错误原因\n3,所属部门,本校未找到部门\n')
            elif url.endswith('/commit'):
                counters['commit_posts']+=1;state['committed']=True;route.abort('connectionreset')
            elif url.endswith('/import') and method=='POST':
                counters['uploads']+=1;route.fulfill(content_type='application/json',status=201,body=json.dumps({'data':preview}))
            elif url.endswith('/'+JID):
                counters['status_gets']+=1;route.fulfill(content_type='application/json',body=json.dumps({'data':completed if state['committed'] else preview}))
            elif '/api/hr/v1/staff?' in url:
                route.fulfill(content_type='application/json',body=json.dumps({'items':[],'total':0,'page':1,'dataBasis':'TEST_FIXTURE','asOf':'2026-09-17'}))
            else:route.fulfill(status=404,body='fixture route not defined')
        page.route('http://127.0.0.1:8765/**',route_handler)
        page.goto('http://127.0.0.1:8765/first-use')
        expect(page.locator('[data-progress-state="NEEDS_STAFF"]').count()==1,'server state not rendered')
        page.locator('.sysadmin-checklist button').click()
        expect(page.locator('[data-progress-state="NEEDS_STAFF"]').count()==1,'memo changed server state')
        page.reload();expect(page.locator('[data-progress-state="NEEDS_STAFF"]').count()==1,'reload fabricated completion')
        page.locator('.first-use-later summary').click()
        expect('不会自动生成虚假地址' in page.locator('.first-use-later').inner_text(),'optional fields note missing')
        page.screenshot(path=str(ART/'first-use-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        expect(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'),'mobile horizontal overflow')
        page.screenshot(path=str(ART/'first-use-mobile.png'),full_page=True)
        checks.extend(['server_state_rendered','memo_cannot_complete_server_steps','reload_retains_server_state','optional_profile_collapsed','mobile_no_overflow'])
        page.set_viewport_size({'width':1440,'height':1100});page.goto('http://127.0.0.1:8765/staff-page')
        page.locator('#importToggle').click();expect(page.locator('#importCommit').is_disabled(),'commit before preview')
        with page.expect_download() as download:page.locator('#downloadTemplate').click()
        download.value.save_as(ART/'browser-downloaded-template.xlsx')
        expect((ART/'browser-downloaded-template.xlsx').read_bytes()==(ROOT/'backend/hr_staff/resources/staff_import_template.xlsx').read_bytes(),'wrong template download')
        page.locator('#importFile').set_input_files({'name':'交互夹具.csv','mimeType':'text/csv','buffer':'姓名,所属部门,人员类别,聘用关系,入职日期\n合成验收人员,数学系,教师,合同聘用,2026-09-01\n合成失败行,不存在部门,教师,合同聘用,2026-09-01\n'.encode()})
        page.locator('#importValidate').click();page.wait_for_function('!document.getElementById("importCommit").disabled')
        expect(page.locator('#importIssues img').count()==0,'error text XSS')
        expect(counters['commit_posts']==0,'upload auto-committed')
        page.screenshot(path=str(ART/'import-preview.png'),full_page=True)
        page.locator('#importCommit').click();expect(counters['commit_posts']==0,'cancel did not cancel')
        state['dialog']='accept';page.locator('#importCommit').click()
        page.wait_for_function('document.getElementById("notice").textContent.includes("尚不能确认提交结果")')
        expect(page.locator('#importCommit').is_disabled(),'timeout allows blind repeated commit')
        expect(page.evaluate('sessionStorage.getItem("hr03.pending-import:7:1")')==JID,'lost job after timeout')
        page.screenshot(path=str(ART/'import-connection-loss.png'),full_page=True)
        page.locator('#importRefresh').click();page.wait_for_function('document.getElementById("importSummary").textContent.includes("当前正式记录可回读 1 行")')
        expect(counters['commit_posts']==1,'refresh repeated POST')
        with page.expect_download() as download:page.locator('#importErrors').click()
        download.value.save_as(ART/'browser-downloaded-errors.csv')
        page.reload();page.wait_for_function('document.getElementById("importSummary").textContent.includes("当前正式记录可回读 1 行")')
        expect(counters['commit_posts']==1,'reload re-committed')
        page.screenshot(path=str(ART/'import-result-recovered.png'),full_page=True)
        page.locator('#importFile').set_input_files({'name':'changed.csv','mimeType':'text/csv','buffer':'姓名\n新夹具\n'.encode()})
        expect(page.locator('#importCommit').is_disabled(),'file replacement reused old preview')
        checks.extend(['template_download_actual_bytes','no_commit_before_preview','preview_escaped_errors','confirmation_cancel','lost_response_blocks_blind_retry','job_id_retained','GET_recovers_result_without_POST','error_download','reload_queries_not_recommits','file_change_invalidates_preview'])
        expect(not errors,'JavaScript errors: '+str(errors))
        browser.close()
    report={'status':'PASS','checks':checks,'count':len(checks),'counters':counters,'page_errors':errors,
        'real_chromium':True,'real_application_templates_and_scripts':True,'api_responses':'SIMULATED_FIXTURE',
        'django_runtime':False,'mysql_runtime':False,'production_accepted':False}
    (ART/'chromium-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
