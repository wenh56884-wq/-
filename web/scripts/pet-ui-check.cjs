/* eslint-disable */
// web/scripts/pet-ui-check.cjs
// 职责：宠物前端交互冒烟——登录 → 跑腿面板 → 指令直达 → 气泡承接，逐项报 PASS/FAIL。
// 说明：
//   1) 独立于项目 node_modules 运行（不往 package.json 加 playwright 依赖）：
//      $env:NODE_PATH = npx 缓存里 playwright 的 node_modules 路径，然后
//      node web/scripts/pet-ui-check.cjs
//      一键方式（PowerShell）：
//      $n = (Get-ChildItem "$env:LOCALAPPDATA\npm-cache\_npx" -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'node_modules\playwright') } | Select-Object -First 1).FullName
//      $env:NODE_PATH = Join-Path $n 'node_modules'; node web/scripts/pet-ui-check.cjs
//   2) 前置：dev server（npm run dev，默认 5173）或 FastAPI 单服务（用 --base 指定）。
//      浏览器走系统 Edge（--channel=msedge），不额外下载 Chromium。
//   3) 登录用 README 公开的演示账号 AI20260001（统一口令 123456h）。
//   4) 退出码：0 全通过；1 有失败项。
// 用法：node web/scripts/pet-ui-check.cjs [--base http://localhost:5173]

const { chromium } = require('playwright')

const base = (() => {
  const i = process.argv.indexOf('--base')
  return i > 0 ? process.argv[i + 1] : 'http://localhost:5173'
})()

const results = []
function check(name, ok, note = '') {
  results.push(Boolean(ok))
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}` + (note ? `  — ${note}` : ''))
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
  try {
  // 1 登录（落地门 → 演示账号一键填充 → 提交）
  await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /开始使用|进入/ }).first().click().catch(async () => {
    await page.locator('button').first().click()
  })
  await page.waitForTimeout(400)
  await page.getByText('AI20260001', { exact: false }).first().click()
  await page.waitForTimeout(400)
  await page.locator('.login-btn').click()
  await page.waitForURL('**/student**', { timeout: 15000 })
  check('登录跳转学生端', page.url().includes('/student'))
  await page.waitForTimeout(2000)

  // 2 大一新生引导：跳过（不挡交互）
  const skipGuide = page.getByRole('button', { name: '跳过新生引导' })
  if (await skipGuide.isVisible().catch(() => false)) await skipGuide.click()
  await page.waitForTimeout(500)

  // 3 宠物在场：角标 + 渲染容器
  check('宠物浮层已挂载', await page.locator('.pet-root').isVisible())
  check('AI 角标正确', (await page.locator('.pet-badge').textContent().catch(() => ''))?.trim() === 'AI')
  check('跑腿按钮已出现（登录态可用）', await page.getByRole('button', { name: '跑腿' }).isVisible().catch(() => false))

  // 4 跑腿面板：打开 → 学生端指令齐备（不含教师专属）
  await page.getByRole('button', { name: '跑腿' }).click()
  await page.waitForTimeout(400)
  check('跑腿面板弹出', await page.locator('.pet-pad').isVisible())
  const chips = await page.locator('.pad-chip').allTextContents()
  check('学生端指令 9 条（成绩单…问 AI）', chips.length === 9 && chips.includes('成绩单') && chips.includes('问 AI'),
    chips.join('/'))
  check('教师专属指令不混入', !chips.includes('学生档案') && !chips.includes('工作流审批'))

  // 5 指令直达：成绩单 → /student/grades + 气泡承接
  await page.locator('.pad-chip', { hasText: '成绩单' }).click()
  await page.waitForURL('**/student/grades**', { timeout: 8000 })
  check('指令直达成绩单页', page.url().includes('/student/grades'))
  await page.waitForTimeout(600)
  const bubble = await page.locator('.pet-bubble').textContent().catch(() => '')
  check('宠物气泡承接', Boolean(bubble && bubble.includes('成绩单')), bubble?.trim().slice(0, 30))
} catch (err) {
  check('流程中断', false, String(err).split('\n')[0].slice(0, 120))
} finally {
  // 截图放 logs/（不入库）：失败时人工排查用
  await page.screenshot({ path: 'logs/pet-ui-check-last.png' }).catch(() => {})
  await browser.close()
}
}

main().then(() => {
  const failed = results.filter((ok) => !ok).length
  console.log(`\n宠物 UI 冒烟：${results.length - failed}/${results.length} 通过`)
  process.exit(failed ? 1 : 0)
}).catch((err) => {
  console.error('致命错误：', String(err).split('\n')[0])
  process.exit(1)
})
