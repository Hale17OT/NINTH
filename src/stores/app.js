import { acceptHMRUpdate, defineStore } from 'pinia'
import { api } from '../services/api'

const preferredTheme = () => localStorage.getItem('theme') || 'dark'

export const useAppStore = defineStore('app', {
  state: () => ({
    dashboard: null,
    scoreboard: null,
    loading: false,
    scoreboardLoading: false,
    error: null,
    syncError: null,
    theme: preferredTheme(),
  }),
  actions: {
    async load(force = false) {
      if (this.loading || (this.dashboard && !force)) return
      this.loading = true
      if (!this.dashboard) this.error = null
      try {
        this.dashboard = await api.dashboard()
        this.error = null
        this.syncError = null
      } catch (error) {
        if (this.dashboard || this.scoreboard) this.syncError = error.message
        else this.error = error.message
      } finally {
        this.loading = false
      }
    },
    async loadScoreboard(force = false) {
      if (this.scoreboardLoading || (this.scoreboard && !force)) return
      this.scoreboardLoading = true
      if (!this.scoreboard && !this.dashboard) this.error = null
      try {
        this.scoreboard = await api.scoreboard()
        this.error = null
        this.syncError = null
      } catch (error) {
        if (this.scoreboard || this.dashboard) this.syncError = error.message
        else this.error = error.message
      } finally {
        this.scoreboardLoading = false
      }
    },
    applyTheme() {
      const root = document.documentElement
      root.classList.toggle('dark', this.theme === 'dark')
      root.classList.toggle('light', this.theme === 'light')
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem('theme', this.theme)
      this.applyTheme()
    },
  },
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useAppStore, import.meta.hot))
