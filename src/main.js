import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.js'
import { useAuthStore } from './features/auth/stores/auth'
import './assets/main.css'
import './assets/builder-system.css'
import './features/auth/auth.css'
import './features/auth/auth-responsive.css'

// Apply the persisted theme before Vue mounts. This boot-critical work must not
// depend on a component action that may temporarily be stale during hot reload.
const initialTheme = localStorage.getItem('theme') || 'dark'
document.documentElement.classList.toggle('dark', initialTheme === 'dark')
document.documentElement.classList.toggle('light', initialTheme === 'light')

const app = createApp(App)
app.config.errorHandler = (error, instance, info) => console.error(`[NINTH] ${info}`, error)
const pinia = createPinia()
app.use(pinia)
const bootstrap = async () => {
  await useAuthStore(pinia).hydrate()
  app.use(router).mount('#app')
}
bootstrap()

// Keep global search keyboard-friendly even in browsers that do not perform
// implicit form submission for a single input without a submit button.
document.addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.matches('.search input')) {
    const query = event.target.value.trim()
    if (query) router.push({ path: '/search', query: { q: query } })
  }
})
