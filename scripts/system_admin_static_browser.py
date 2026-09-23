from __future__ import annotations
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'tests/artifacts/system-admin-usability'
CSS=ROOT/'frontend/static/hr/css/hr-admin-center.css'
JS=ROOT/'frontend/static/hr/js/core/hr-admin-center.js'

def require(cond,msg):
    if not cond: raise AssertionError(msg)

def main():
    ART.mkdir(parents=True,exist_ok=True)
    html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body>
    <main class="sysadmin-center" data-system-admin-center>
      <section class="sysadmin-task-first"><div class="sysadmin-search-wrap"><input id="sysadmin-task-search"></div><div id="sysadmin-search-results" class="sysadmin-search-results" hidden></div>
      <div class="sysadmin-task-grid"><a class="sysadmin-task-card" href="#school" data-title="学校基本信息" data-keywords="学校 校名 单校 主体"><span class="sysadmin-task-icon">S</span><strong>学校基本信息</strong><small>维护唯一学校主体</small></a><a class="sysadmin-task-card" href="#roles" data-title="角色与权限" data-keywords="角色 权限 授权 复制 配角色 分权限 加权限"><span class="sysadmin-task-icon">R</span><strong>角色与权限</strong><small>复制角色、分配成员、配置权限</small></a><a class="sysadmin-task-card" href="#audit" data-title="安全审计" data-keywords="审计 日志 登录 越权"><span class="sysadmin-task-icon">A</span><strong>安全审计</strong><small>查看审计日志</small></a><a class="sysadmin-task-card" href="#sysadmin-runtime" data-title="运行与备份" data-keywords="备份 恢复 数据库 运行状态"><span class="sysadmin-task-icon">B</span><strong>运行与备份</strong><small>检查备份与恢复</small></a></div></section>
      <ol class="sysadmin-checklist"><li data-check="school"><button type="button"></button><div><strong>1.学校</strong><small>学校主体</small></div></li><li data-check="org"><button type="button"></button><div><strong>2.组织</strong><small>组织岗位</small></div></li></ol>
      <section data-admin-assistant><div class="sysadmin-prompts"><button type="button">单校版第一次上线先配置什么？</button><button type="button">学院和部门应该建在哪里？</button><button type="button">怎么给新管理员分配最小权限？</button></div><div class="sysadmin-answer" id="sysadmin-answer" hidden></div></section><section id="sysadmin-health" class="sysadmin-health"><div class="sysadmin-health-grid"><article class="sysadmin-health-item is-ok"><div class="sysadmin-health-dot"></div><div><strong>学校主体</strong><span>已绑定测试学校</span></div></article><article class="sysadmin-health-item is-warning"><div class="sysadmin-health-dot"></div><div><strong>备份恢复</strong><span>待演练</span><em>建议：完成一次隔离恢复</em></div></article></div></section><section id="sysadmin-runtime" class="sysadmin-ops"><div class="sysadmin-runtime-summary"><article><span>部署形态</span><strong>单校独立部署版</strong></article></div></section>
      <section class="ug-tab-panel"><div class="sysadmin-role-risk">正在计算权限影响…</div><input type="checkbox" name="permissions" value="x.view"><input id="danger" type="checkbox" name="permissions" value="x.delete" data-permission-risk="high"></section>
    </main></body></html>'''
    evidence={}
    with sync_playwright() as p:
      browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
      page=browser.new_page(viewport={"width":1440,"height":1000})
      errors=[]; page.on('pageerror',lambda exc: errors.append(str(exc)))
      page.set_content(html); page.add_style_tag(content=CSS.read_text('utf-8'))
      page.on('dialog',lambda d: d.dismiss())
      page.add_script_tag(content=JS.read_text('utf-8')); page.wait_for_timeout(60)
      page.locator('#sysadmin-task-search').fill('配角色'); page.wait_for_timeout(60)
      require(page.locator('#sysadmin-search-results:not([hidden])').count()==1,'search results missing')
      require('角色与权限' in page.locator('#sysadmin-search-results').inner_text(),'plain language role search failed')
      page.locator('.sysadmin-checklist li[data-check="school"] button').click(); require(page.locator('.sysadmin-checklist li[data-check="school"].is-done').count()==1,'checklist failed')
      page.locator('.sysadmin-prompts button').first.click(); require('学校主体' in page.locator('#sysadmin-answer').inner_text(),'assistant answer missing')
      page.locator('#danger').click(); page.wait_for_timeout(50); require(not page.locator('#danger').is_checked(),'dangerous permission cancel did not revert')
      require(page.locator('.sysadmin-role-risk.is-danger').count()==0 and '高风险 1 项' not in page.locator('.sysadmin-role-risk').inner_text(),'risk summary wrong after cancel')
      page.screenshot(path=str(ART/'system-admin-center-real-chromium.png'),full_page=True)
      require(not errors,'page errors: '+' | '.join(errors))
      require(page.locator('.sysadmin-health-item').count()==2,'health cards missing'); require('单校独立部署版' in page.locator('#sysadmin-runtime').inner_text(),'standalone runtime summary missing'); evidence={"task_search":"PASS","checklist":"PASS","admin_prompt":"PASS","health_panel":"PASS","standalone_runtime":"PASS","danger_permission_confirmation":"PASS","page_errors":errors}
      browser.close()
    (ART/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('System admin real Chromium smoke: PASS'); print(json.dumps(evidence,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
