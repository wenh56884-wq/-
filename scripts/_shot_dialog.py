import json, urllib.request, os
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8000"
tok=json.loads(urllib.request.urlopen(urllib.request.Request(BASE+"/auth/login",data=json.dumps({"role":"teacher","account":"T001","password":"123456h"}).encode(),headers={"Content-Type":"application/json"})).read())["access_token"]
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1500,"height":1000},device_scale_factor=2, accept_downloads=True); pg=ctx.new_page()
    pg.goto(BASE+"/login"); pg.evaluate("(t)=>{localStorage.setItem('qh_token',t);localStorage.setItem('qh_role','teacher');localStorage.setItem('qh_tenant_id','1')}", tok)
    pg.goto(BASE+"/teacher?tab=grades"); pg.wait_for_timeout(3500)
    pg.get_by_role("button", name="全班成绩").click(); pg.wait_for_timeout(500)
    pg.locator('.el-dropdown-menu__item:visible:has-text("自选字段")').first.click(); pg.wait_for_timeout(1800)
    pg.locator(".el-dialog").screenshot(path="shots/local/export-04-zoom.png")
    b.close()
