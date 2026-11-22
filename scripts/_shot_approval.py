import json, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

import os
BASE=os.environ.get("QH_BASE","http://127.0.0.1:8000")
OUT_DIR="shots/online" if "101." in BASE else "shots/local"
OUT=Path(OUT_DIR); OUT.mkdir(parents=True, exist_ok=True)

def login(role, account):
    req=urllib.request.Request(BASE+"/auth/login", data=json.dumps(
        {"role":role,"account":account,"password":"123456h"}).encode(),
        headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req).read())["access_token"]

errs=[]
with sync_playwright() as p:
    b=p.chromium.launch()
    # 教师端
    ctx=b.new_context(viewport={"width":1500,"height":1000}, device_scale_factor=2)
    pg=ctx.new_page()
    pg.on("console", lambda m: errs.append("T:"+m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append("T:"+str(e)))
    tok=login("teacher","T001")
    pg.goto(BASE+"/login")
    pg.evaluate("(t)=>{localStorage.setItem('qh_token',t);localStorage.setItem('qh_role','teacher');localStorage.setItem('qh_tenant_id','1')}", tok)
    pg.goto(BASE+"/teacher/approvals"); pg.wait_for_timeout(3000)
    pg.screenshot(path=str(OUT/"wf-01-guide-pending.png"))
    pg.locator(".el-table__row").first.locator(".el-table__expand-icon").click()
    pg.locator(".expand-body").first.wait_for(timeout=4000)
    pg.wait_for_timeout(900)
    pg.screenshot(path=str(OUT/"wf-02-expanded.png"))
    pg.locator(".el-tabs__item", has_text="最近处理").click()
    pg.wait_for_timeout(1200)
    pg.screenshot(path=str(OUT/"wf-03-history.png"))
    ctx.close()
    # 学生端
    ctx2=b.new_context(viewport={"width":1500,"height":1100})
    pg2=ctx2.new_page()
    pg2.on("console", lambda m: errs.append("S:"+m.text) if m.type=="error" else None)
    pg2.on("pageerror", lambda e: errs.append("S:"+str(e)))
    tok2=login("student","AI20230001")
    pg2.goto(BASE+"/login")
    pg2.evaluate("(t)=>{localStorage.setItem('qh_token',t);localStorage.setItem('qh_role','student');localStorage.setItem('qh_student_no','AI20230001')}", tok2)
    pg2.goto(BASE+"/student"); pg2.wait_for_timeout(4000)
    card = pg2.locator(".wf-card")
    if card.count():
        card.scroll_into_view_if_needed(); pg2.wait_for_timeout(600)
        card.screenshot(path=str(OUT/"wf-04-student-card.png"))
        print("学生流程卡 OK")
    else:
        print("!! 学生流程卡未出现")
    b.close()
print("errors:", errs[:6] if errs else "none")
