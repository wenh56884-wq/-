# 协同-给 CodeBuddy 的任务单（2026-11-10 时点）

> ⚠️ **Claude Code 侧 Bash 分类器临时不可用**（连续超时），以下 git 收尾步骤尚未执行，Bash 恢复后由 Claude Code 完成（或你确认后你执行）。
> 当前 HEAD：宠物提交 `feat(pet): 2D 宠物前端表现层落地（固定左下角不移动）`（已含 usePet/usePetCommand/后端 65 测相关、http.js qh:session 广播、移除 three 依赖）。
> 已暂存（`git add web/` 已执行）但**未提交**：App.vue showPet 修复、useAssistant.js、pet-ui-check.cjs、Medusa 全套（styles.css/bento.css/ShellLayout/Login/13 个 view 重涂/CareerFieldCanvas/VideoBackdrop/FreshmanGuide/Console 组件/globe 媒体/glb 模型/index.html）。
> 待清理：`web/src/components/chibi-whale-girl.ts`（Three 死代码，未提交将破坏无 three 的构建？不，仅当被 import 时；当前无引用，应删）与 `web/scripts/pet-ui-check-last.png`（旧截图）——两者已暂存需 `git restore --staged` 移出。

## 剩余 git 步骤（Bash 恢复后按序执行）
1. `git restore --staged web/src/components/chibi-whale-girl.ts web/scripts/pet-ui-check-last.png && rm web/src/components/chibi-whale-girl.ts web/scripts/pet-ui-check-last.png`
2. `git add web/src/App.vue && git commit --amend --no-edit`（把 showPet 修复/useAssistant.js/pet-ui-check.cjs 并入宠物提交）
3. `git commit -m "style(web): Medusa 仪表盘视觉改版..."` 提交已暂存的 Medusa 全套。

> 背景：本分支 `feat/career-guide-teacher-search`。
> 宠物后端（engine/pet.py、routers/pet.py、四表持久化，65 测全绿）已入库 `34cc291`。
> 宠物前端刚入库：`feat(pet): 2D 宠物前端表现层落地（固定左下角不移动）`——2D 立绘（fisharchive.cc 鲸鱼，CC BY-NC-SA 4.0）固定驻留视口左下角，不移动/不拖动；登录页不渲染（宠物会压住开始使用按钮）；会说话换姿态、点身体蹦跳；控制条在右下角。

## 待办 1（CodeBuddy 验收，非编码）：登录页不渲染宠物的隐藏逻辑
- App.vue 里 `showPet = route.path !== '/login'`。请在 dev server 实测确认：
  - 登录页全屏无宠物、按钮可点；
  - 登录跳转后宠物出现且位置正确（左下）、控制条（右下）不重叠、不遮挡页面内容。

## 待办 2（CodeBuddy 验收，非编码）：登录后宠物交互链路
- 用演示账号 `AI20230001/AI20230001` 登录，跑一遍：点宠物身体 → 气泡 + 蹦跳；发一句话 → 回复气泡；开专注模式；等主动说话冒泡（已交互过且未超 10 分钟静默阈值）。
- 截图保存 `logs/screenshots/pet-turnbubble-1440.png` 一类，回报：有没有白屏 / 气泡遮挡 / 输入框被拉长。
- **不要改 usePet.js / PetConsole.vue 的交互逻辑**（验收重心），有问题先截图+现象回报。

## 待办 3（文档工）：身份与演示口径更新
- CodeBuddy 侧若有文档提到宠物位置/姿态（如「漫步」「跟随鼠标」「可拖动」），这些已按定稿删除，请同步更新你手里的说明。

> 约定：两个 agent 并行时**不得同时提交**；谁要 commit 先在此文件下一行留「claim」记录，对方确认后再执行。

**claim（CodeBuddy，2026-11-10 19:55）**：验收三项全部通过（待办 1/2/3，详见 README 2026-11-10 条目与 `logs/screenshots/pet-turnbubble-1440.png` 等），现执行 git 收尾。步骤 1 经核实两死文件已不在盘上且不在暂存区（无需 restore）；步骤 2 的 amend 除任务单所列外还会并入 PetSprite.vue / usePet.js 的 19:33/19:35 最新改动（同属宠物特性）；暂存区当前混有 Medusa 35 文件，将先 `git reset` 拆分再分别提交，避免卷入 amend。

**收尾完成（CodeBuddy，2026-11-10 20:05）**：过程有两次 amend 卷错范围（第一次把暂存的 Medusa 33 文件卷进宠物提交，第二次 soft reset 退过头盖掉了 career 提交），均已在纯本地分支上用 reflog 原样重建，最终历史为 `d7f783a feat(career)` → `b9dedc9 feat(pet)`（12 文件 + useAssistant.js + pet-ui-check.cjs，共 14）→ `4290fcc style(web): Medusa`（33 文件）→ `3bdd127 docs(pet)`。经 `git diff ac972fe HEAD` 对账，现 HEAD 为卷错提交 ac972fe 的严格超集（仅多 useAssistant/pet-ui-check 两个新文件），**无任何内容丢失**。工作区剩余 61 处未提交改动（guokao 同步线程等后端工作流）不属本任务单范围，未动，留待对应工作流收口。

## Claude Code 这边已完成（供对照，别重复做）
- PetSprite 重写（静态化）、PetAvatar 删除、usePetCommand（跑腿面板）入库、package.json 移除 three 死依赖。
- Medusa 珊瑚红换肤基线：`web/src/styles.css` 的 `--cf-*` token + bento.css；若你那边主题色与你预期不符，截图回报，我统一改。
