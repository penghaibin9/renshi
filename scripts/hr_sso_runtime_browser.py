#!/usr/bin/env python3
"""Browser acceptance for the real Yueke HR SSO runtime against CI mock OIDC."""
from __future__ import annotations
import json, os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

BASE=os.getenv("HR_V1_BROWSER_BASE_URL","http://127.0.0.1:8000").rstrip("/")
ART=Path(os.getenv("HR_V1_BROWSER_ARTIFACT_DIR","tests/artifacts/hr-config-integration-v1"))
SSO_NAME=os.getenv("HR_SSO_CI_CONNECTION_NAME","CI OIDC 统一认证")

def require(cond,msg):
    if not cond: raise AssertionError(msg)

def main():
    ART.mkdir(parents=True,exist_ok=True);errors=[];console=[];evidence=[];failure=None
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);ctx=browser.new_context(viewport={"width":1440,"height":1000})
        ctx.tracing.start(screenshots=True,snapshots=True,sources=True);page=ctx.new_page()
        page.on("pageerror",lambda exc:errors.append(str(exc)));page.on("console",lambda msg:console.append(msg.text) if msg.type=="error" else None)
        try:
            r=page.goto(BASE+"/login/",wait_until="domcontentloaded");require(r and r.status==200,"login unavailable")
            button=page.locator("a.yk-login-submit--sso",has_text=SSO_NAME).first
            require(button.count()==1,"SSO button missing from public login")
            with page.expect_navigation(wait_until="domcontentloaded",timeout=15000): button.click()
            page.wait_for_load_state("domcontentloaded")
            require(urlsplit(page.url).path!="/login/","SSO returned to login instead of authenticated page")
            require(any(c["name"]=="sessionid" for c in ctx.cookies()),"session cookie missing after SSO")
            evidence.append({"step":"oidc-browser-login","status":"PASS","finalUrl":page.url})
            page.screenshot(path=str(ART/"03-sso-runtime-success.png"),full_page=True)
            r=page.goto(BASE+"/settings/integration-hub/",wait_until="domcontentloaded");require(r and r.status==200,"Integration Hub unavailable after SSO")
            body=page.locator("body").inner_text();require("接口适配中心" in body or "Integration" in body,"authenticated SSO session cannot access expected system page")
            page.goto(BASE+"/sso/logout/",wait_until="domcontentloaded")
            require(urlsplit(page.url).path=="/login/","local SSO logout did not return to login")
            evidence.append({"step":"local-sso-logout","status":"PASS"})
        except BaseException as exc:
            failure=exc
        finally:
            ctx.tracing.stop(path=str(ART/"sso-trace.zip"));browser.close()
    result={"status":"FAIL" if failure else "PASS","evidence":evidence,"pageErrors":errors,"consoleErrors":console}
    (ART/"sso-runtime-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    require(not errors,f"page errors: {errors}");require(not console,f"console errors: {console}")
    if failure: raise failure
if __name__=="__main__": main()
