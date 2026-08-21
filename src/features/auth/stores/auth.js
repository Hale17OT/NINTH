import { acceptHMRUpdate, defineStore } from 'pinia'
import { api } from '../../../services/api'
import { trackAuthEvent } from '../services/authAnalytics'

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null, hydrated: false, loading: false, config: { googleConfigured: false, emailConfigured: false }, error: null }),
  getters: {
    isAuthenticated: state => Boolean(state.user),
    initials: state => state.user?.displayName?.split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase() || 'N',
  },
  actions: {
    async hydrate(force = false) {
      if (this.hydrated && !force) return this.user
      try {
        const [session, config] = await Promise.all([api.authMe(), api.authConfig().catch(() => this.config)])
        this.user = session.user
        this.config = config
      } catch {
        this.user = null
      } finally {
        this.hydrated = true
      }
      return this.user
    },
    async login(payload) {
      this.loading = true; this.error = null; trackAuthEvent('auth_sign_in_started')
      try {
        const response = await api.authLogin(payload)
        this.user = response.user; this.hydrated = true; trackAuthEvent('auth_sign_in_completed')
        return response.user
      } catch (error) { this.error = error; trackAuthEvent('auth_failed', { flow: 'sign_in', code: error.status }); throw error }
      finally { this.loading = false }
    },
    async register(payload) {
      this.loading = true; this.error = null; trackAuthEvent('auth_sign_up_started')
      try {
        const response = await api.authRegister(payload)
        this.user = response.user; this.hydrated = true; trackAuthEvent('auth_sign_up_completed')
        return response
      } catch (error) { this.error = error; trackAuthEvent('auth_failed', { flow: 'sign_up', code: error.status }); throw error }
      finally { this.loading = false }
    },
    async loginWithGoogle(returnTo = '/', remember = true) {
      this.loading = true; this.error = null; trackAuthEvent('auth_google_started')
      try {
        const { url } = await api.authGoogleUrl(returnTo, remember)
        window.location.assign(url)
      } catch (error) { this.error = error; this.loading = false; trackAuthEvent('auth_failed', { flow: 'google', code: error.status }); throw error }
    },
    async logout() {
      try { await api.authLogout() } finally { this.user = null; this.hydrated = true; trackAuthEvent('auth_logout') }
    },
    async refreshUser() { return this.hydrate(true) },
    setUser(user) { this.user = user; this.hydrated = true },
  },
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useAuthStore, import.meta.hot))
