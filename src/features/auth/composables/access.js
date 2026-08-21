import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import { safeReturnTo } from '../utils/returnTo.js'

export { safeReturnTo }

export const featureRules = Object.freeze({
  buildBest5: { public: true },
  dailyModelPerformance: { public: true },
  advancedBuilders: { requiresAuth: true },
  savedContent: { requiresAuth: true },
  accountSettings: { requiresAuth: true },
})

export const useRequireAuth = () => {
  const auth = useAuthStore()
  const router = useRouter()
  const route = useRoute()
  const promptOpen = ref(false)
  const pendingAction = ref(null)
  const requireAuth = action => {
    if (auth.isAuthenticated) return action?.()
    pendingAction.value = action || null
    promptOpen.value = true
    return false
  }
  const signIn = () => router.push({ path: '/auth/sign-in', query: { returnTo: safeReturnTo(route.fullPath) } })
  return { isAuthenticated: computed(() => auth.isAuthenticated), promptOpen, pendingAction, requireAuth, signIn }
}
