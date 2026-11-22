# scripts/verify_export_render.py
# 职责：Playwright 验证「一键下载」在学生档案页与成绩页可见、可点、真能下到文件
# 铁律：只读验证，不改数据；下载文件落到 logs/export_render/ 供人工复核
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "logs" / "export_render"
OUT.mkdir(parents=True, exist_ok=True)


def login(page, demo_label: str) -> None:
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.evaluate("localStorage.clear()")
    page.reload(wait_until="domcontentloaded")
    page.get_by_text(demo_label, exact=False).first.click()
    page.click(".login-btn")
    page.wait_for_url(lambda url: "/login" not in url, timeout=25000)


def pick_first_class(page) -> None:
    """班级下拉点开选第一个，保证筛选有值，导出按钮才可用。"""
    try:
        sel = page.get_by_placeholder("请选择班级").first
        sel.click()
        page.wait_for_timeout(600)
        page.locator(".el-select-dropdown__item").first.click()
        page.wait_for_timeout(1500)
    except PWTimeout:
        print("  (跳过选班级：可能已有默认班级)")


def try_download(page, trigger_text: str, item_text: str, tag: str) -> None:
    page.get_by_text(trigger_text, exact=False).first.click()
    page.wait_for_timeout(600)
    # 只点「当前可见」的下拉项：页面上会同时存在多个下拉的 DOM（之前打开的没销毁），
    # get_by_text 会优先命中隐藏的那个，点不动
    item = page.locator(f".el-dropdown-menu__item:visible", has_text=item_text).first
    with page.expect_download(timeout=30000) as info:
        item.click()
    download = info.value
    target = OUT / f"{tag}-{download.suggested_filename}"
    download.save_as(str(target))
    size = target.stat().st_size
    print(f"  [download ok] {tag}: {download.suggested_filename} ({size:,} B)")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                accept_downloads=True)

        # ---------------- 学生档案页
        login(page, "教师：T001")
        page.goto(f"{BASE}/teacher/students", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        pick_first_class(page)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "01-students-page.png"), full_page=False)

        btn = page.get_by_text("下载名单", exact=False).first
        print(f"  「下载名单」按钮可见={btn.is_visible()} 可用={btn.is_enabled()}")

        try:
            try_download(page, "下载名单", "Excel", "students")
            page.screenshot(path=str(OUT / "02-students-after-download.png"))
        except Exception as exc:  # noqa: BLE001
            print(f"  !! 学生档案下载失败：{type(exc).__name__} {exc}")
            page.screenshot(path=str(OUT / "02-students-download-failed.png"))

        # ---------------- 成绩页
        page.goto(f"{BASE}/teacher/grades", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "03-grades-page.png"), full_page=False)

        # 全班成绩导出
        try:
            try_download(page, "全班成绩", "Excel", "class-grades")
        except Exception as exc:  # noqa: BLE001
            print(f"  !! 全班成绩下载失败：{type(exc).__name__} {exc}")

        # 选一名学生后导出个人成绩单
        try:
            # el-select 的 placeholder 在内部 input 上，用组件序号定位更稳：
            # 筛选卡里依次是 班级 / 学生 / 学期
            # el-select 外层容器常被判定为不可见，直接点内部 input 最稳；
            # 筛选卡内依次是 班级 / 学生 / 学期 三个输入
            inputs = page.locator(".filter-card input")
            print(f"  筛选卡输入框数量={inputs.count()}")
            inputs.nth(1).click()
            page.wait_for_timeout(800)
            options = page.locator(".el-select-dropdown__item:visible")
            print(f"  学生下拉选项数={options.count()}")
            options.first.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / "04a-after-pick.png"))
            # 成绩单卡片（含「下载成绩单」）要等查询出 report 才渲染
            qbtn = page.get_by_text("查询成绩", exact=True).first
            print(f"  「查询成绩」可见={qbtn.is_visible()} 可用={qbtn.is_enabled()}")
            qbtn.click()
            page.wait_for_timeout(3500)
            page.screenshot(path=str(OUT / "04-grades-student-picked.png"))
            try_download(page, "下载成绩单", "Excel", "student-grades")
            page.screenshot(path=str(OUT / "05-grades-after-download.png"))
        except Exception as exc:  # noqa: BLE001
            print(f"  !! 个人成绩单下载失败：{type(exc).__name__} {exc}")
            page.screenshot(path=str(OUT / "05-grades-failed.png"))

        browser.close()

    files = sorted(OUT.glob("*.xlsx"))
    print(f"\n下载落盘 {len(files)} 个文件 -> {OUT}")
    for f in files:
        print(f"  {f.name}  {f.stat().st_size:,} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
