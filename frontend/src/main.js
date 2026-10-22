import './index.css'
import './styles/pramaan.css'
import { createApp, watch } from 'vue'
import router from './router'
import App from './App.vue'
import { createPinia } from 'pinia'
import dayjs from '@/utils/dayjs'
import '@fontsource-variable/fraunces'
import '@fontsource/geist-sans/400.css'
import '@fontsource/geist-sans/500.css'
import '@fontsource/geist-sans/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import { createDialog } from '@/utils/dialogs'
import translationPlugin from './translation'
import { usersStore } from './stores/user'
import { initSocket } from './socket'
import { FrappeUI, setConfig, frappeRequest } from 'frappe-ui'
import { registerDirectives } from './directives'

let pinia = createPinia()
let app = createApp(App)
setConfig('resourceFetcher', frappeRequest)
setConfig('maxFileSize', window.max_file_size)

app.use(FrappeUI)
app.use(pinia)
app.use(router)
app.use(translationPlugin)
registerDirectives(app)
app.provide('$dayjs', dayjs)
app.provide('$socket', initSocket())
app.mount('#app')

const { userResource, allUsers } = usersStore()
app.provide('$user', userResource)
app.provide('$allUsers', allUsers)

app.config.globalProperties.$user = userResource
app.config.globalProperties.$dialog = createDialog
