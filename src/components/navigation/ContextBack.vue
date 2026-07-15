<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'

const props = defineProps({ fallback: { type: String, default: '/' } })
const route = useRoute()
const router = useRouter()
const previous = computed(() => { route.fullPath; return window.history.state?.back || null })
const destination = computed(() => previous.value || props.fallback)
const destinationLabel = computed(() => {
  const path = destination.value.split('?')[0]
  if (path === '/') return 'HOME'
  if (path === '/builder') return 'BUILDER'
  if (path === '/schedule' || path.startsWith('/games/')) return 'GAMES'
  if (path === '/live') return 'LIVE CENTER'
  if (path.startsWith('/live/')) return 'LIVE GAME'
  if (/^\/teams\/[^/]+$/.test(path)) return 'TEAM'
  if (path === '/teams') return 'TEAMS'
  if (/^\/players\/[^/]+$/.test(path)) return 'PLAYER'
  if (path === '/players') return 'PLAYERS'
  if (path === '/standings') return 'STANDINGS'
  if (path === '/model') return 'MODEL LAB'
  if (path === '/slips') return 'MY SLIPS'
  if (path === '/search') return 'SEARCH RESULTS'
  return 'PREVIOUS SCREEN'
})
const goBack = () => previous.value ? router.back() : router.push(props.fallback)
</script>

<template><button class="context-back" type="button" @click="goBack"><ArrowLeft :size="13"/> BACK TO {{ destinationLabel }}</button></template>

<style scoped>
.context-back{display:flex;align-items:center;gap:7px;width:max-content;padding:9px 0;border:0;background:transparent;color:var(--muted);font:700 8px 'DM Mono';letter-spacing:.04em;cursor:pointer}.context-back:hover{color:var(--text)}
</style>
