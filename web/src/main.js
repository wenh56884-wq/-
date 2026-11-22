import { createApp } from 'vue'
import { ElLoading } from 'element-plus/es/components/loading/index.mjs'
// 模板组件样式由 unplugin-vue-components 按需注入；
// 这里补上三个“程序调用”组件的样式：v-loading / ElMessage / ElMessageBox。
import 'element-plus/es/components/loading/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'

import App from './App.vue'
import router from './router'
import './styles/fonts.css'
import './styles.css'
import './styles/bento.css'
import './styles/readability.css'
import './styles/motion.css'
// 科技感层最后引入：在浅色底之上叠加渐变/发光/微动效，覆盖同名动效规则
import './styles/tech.css'

// 组件由 unplugin-vue-components 按需引入；这里只注册全站共用的 v-loading 指令。
// 中文 locale 由 App.vue 的 <el-config-provider :locale="zhCn"> 提供。
createApp(App).use(ElLoading).use(router).mount('#app')
