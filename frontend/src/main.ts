import { createPinia } from 'pinia'
import { createApp } from 'vue'

import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import router from './router'
import './assets/base.css'

createApp(App).use(createPinia()).use(router).use(Antd).mount('#app')
