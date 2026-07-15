import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.js'
import './assets/main.css'
createApp(App).use(createPinia()).use(router).mount('#app')

// Keep global search keyboard-friendly even in browsers that do not perform
// implicit form submission for a single input without a submit button.
document.addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.matches('.search input')) {
    const query = event.target.value.trim()
    if (query) router.push({ path: '/search', query: { q: query } })
  }
})
