import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.js'
import './assets/main.css'

// Apply the persisted theme before Vue mounts. This boot-critical work must not
// depend on a component action that may temporarily be stale during hot reload.
const initialTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
document.documentElement.classList.toggle('dark', initialTheme === 'dark')
document.documentElement.classList.toggle('light', initialTheme === 'light')

const app = createApp(App)
app.config.errorHandler = (error, instance, info) => console.error(`[NINTH] ${info}`, error)
app.use(createPinia()).use(router).mount('#app')

// Keep global search keyboard-friendly even in browsers that do not perform
// implicit form submission for a single input without a submit button.
document.addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.matches('.search input')) {
    const query = event.target.value.trim()
    if (query) router.push({ path: '/search', query: { q: query } })
  }
})
