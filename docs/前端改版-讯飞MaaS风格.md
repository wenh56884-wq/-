# 前端改版任务书：讯飞星辰 MaaS 风格

> 参考：https://maas.xfyun.cn/overview
> 目标：把启航 Web 端从「Bento 便当盒」改成参考站的「冷白 + 紫蓝、顶栏导航、白色圆角卡片、渐变主视觉」风格。
> 约束：只改 `web/`；后端接口、字段名、数值口径一律不动；不引入新的 UI 依赖。

## 0. 当前进度（本轮已做）

- 全局色板/圆角/阴影已切到紫蓝体系：`web/src/styles.css`、`web/src/styles/bento.css`
- 侧边栏、顶栏、AI 问法条、登录页已做第一版换肤：`web/src/layout/ShellLayout.vue`、`web/src/views/Login.vue`
- 聊天抽屉已换肤并支持「执行轨迹」折叠：`web/src/components/ChatDrawer.vue`
- 参考截图：`shots/xfyun_overview.png`；当前效果：`shots/qh_student_theme.png`、`shots/qh_exams_theme2.png`、`shots/qh_gk_drawer.png`、`shots/qh_chat_brain.png`

## 1. 设计 token（必须统一）

```css
--qh-bg: #f5f7fc;
--qh-surface: #ffffff;
--qh-border: #eceef7;
--qh-text: #171a2b;
--qh-text-sub: #5b6178;
--qh-text-mute: #9297ab;
--qh-primary: #5b5bd6;
--qh-primary-soft: #f0eeff;
--qh-radius: 16px;
--qh-shadow: 0 2px 10px rgba(33,40,90,.04), 0 8px 24px rgba(33,40,90,.04);
```

辅助色：浅紫 `#f1efff`、浅蓝 `#e8f6ff`、成功绿 `#16a34a`、预警红/橙/黄保持现有数据语义色，不得改。

标题字重 650，正文 400/500；卡片内边距 20~24px；卡片 hover 只允许 `translateY(-2px)` + 阴影，不缩放。

## 2. 目标结构（桌面）

参考站是「顶栏导航 + 全宽内容」，不是左侧栏。建议：

```
┌──────────────────────────────────────────────────────────┐
│ 启航(渐变 logo)  我的画像  成绩单  岗位库  招考信息 …   状态/头像 │  64px 白色半透明顶栏
├──────────────────────────────────────────────────────────┤
│  渐变 Hero 卡：一句话结论 + 2~3 个关键指标 + 主按钮           │
├──────────────────────────────────────────────────────────┤
│  常用功能（4 列白色卡片，左上角淡紫图标块，右上角 ↗）           │
├──────────────────────────────────────────────────────────┤
│  数据区（沿用现有 bento-grid，White card + 软阴影）             │
└──────────────────────────────────────────────────────────┘
```

- 顶栏：白底 82% 透明 + `backdrop-filter: blur(14px)`；logo 用紫蓝渐变方块；当前路由用浅紫 pill（`#efedff`，文字 `#4f46e5`）。
- 移动端（<1024px）：顶栏收成汉堡 + 抽屉，不保留常驻侧栏。
- 内容区最大宽度 1280px，左右 24~32px 留白。

## 3. 分工建议

### Workbuddy：壳层 + 登录 + 响应式

| 文件 | 任务 |
|---|---|
| `web/src/layout/ShellLayout.vue` | 侧栏改顶栏；导航 pill；用户/状态收进右侧；移动端抽屉；删除 `contentMargin` 相关逻辑 |
| `web/src/views/Login.vue` | 登录页按参考站「左渐变品牌区 + 右白色表单卡」；按钮/单选/演示账号紫蓝化 |
| `web/src/styles.css` | 统一 Element Plus 主题变量、卡片/输入/按钮圆角与聚焦环 |
| `web/src/styles/bento.css` | token 与卡片 hover 收敛；新增 `.hero-card` 工具类 |

### Codebuddy：页面内容 + 组件

| 文件 | 任务 |
|---|---|
| `web/src/views/StudentHome.vue` | 顶部加 Hero 卡（姓名/学期/预警等级/推荐岗位数 + 「查看岗位」「问 AI」两个按钮）；快捷入口改成 4 列图标卡 |
| `web/src/views/TeacherDashboard.vue` | 顶部 Hero 卡（班级数/学生数/预警人数 + 「查看预警名单」）；统计卡统一图标块 |
| `web/src/views/ExamNotices.vue` | 公告统计卡与国考职位入口卡统一参考站卡片样式；抽屉表格保持信息密度 |
| `web/src/views/JobList.vue` | 筛选区做成白色圆角卡；岗位卡左上角行业图标块 + 右上角 ↗ |
| `web/src/components/ChatDrawer.vue` | 头部渐变细条/白色毛玻璃；用户气泡紫蓝渐变；执行轨迹保持可折叠 |

> 不要改 `web/src/api/`、`web/src/router/`、任何 `fetch/axios` 参数与字段名。

## 4. 验收标准

1. `cd web && npm run build` 通过。
2. 1440×1000、1024×768、390×844 三档截图无横向滚动；顶栏不换行。
3. 所有页面主色只出现紫蓝体系（除预警红/橙/黄、成功绿）。
4. 数值、表格字段、接口调用与改版前完全一致（用 `git diff` 只看 `web/`）。
5. 登录 → 学生首页 → 招考页 → 国考职位抽屉 → AI 抽屉，五个页面视觉一致。
6. 不新增 npm 依赖；不引入 Tailwind。

## 5. 已知问题（交给实施方）

- 参考站首屏有 3D 主视觉；启航没有插画资源，Hero 用 CSS 渐变 + 细网格即可，不要外链图片。
- 现有页面信息密度高（尤其招考页/岗位页），Hero 高度控制在 160~200px，别把首屏数据挤到折叠线以下。
- 侧栏改顶栏后，原 `.sidebar` / `.content marginLeft` 相关样式要一起删，避免残留空白。
- 并行协作时按上表「文件所有权」改，避免多人同时改 `ShellLayout.vue`。
