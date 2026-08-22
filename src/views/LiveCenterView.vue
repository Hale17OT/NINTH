<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../services/api'
import GameCard from '../components/game/GameCard.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import LoadError from '../components/ui/LoadError.vue'
import { createSharedPoller } from '../services/polling'
import { LIVE_VIEW_REFRESH_MS } from '../services/pollingPolicy'

const games = ref([])
const loading = ref(true)
const updatedAt = ref()
const error = ref('')
let poller

const load = async () => {
  try {
    error.value = ''
    games.value = await api.games('live')
    updatedAt.value = new Date()
  } catch (caught) {
    error.value = caught?.message || 'The live scoreboard could not be loaded.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  poller = createSharedPoller({ key: 'live-center', task: load, interval: LIVE_VIEW_REFRESH_MS })
  poller.start()
})
onBeforeUnmount(() => poller?.stop())
</script>

<template>
  <div class="live-center">
    <section class="panel hero">
      <div><span class="eyebrow"><i class="live-dot"></i> NINTH / OFFICIAL MLB SCOREBOARD</span><h1>Every live game.<br><em>One pulse.</em></h1><p>Choose a game for pitch tracking, counts, baserunners, and official play-by-play.</p></div>
      <div class="summary"><strong class="mono">{{ games.length }}</strong><span>GAMES LIVE</span><small v-if="updatedAt">Updated {{ updatedAt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) }}</small></div>
    </section>
    <div v-if="games.length" class="game-grid"><GameCard v-for="game in games" :key="game.id" :game="game" live /></div>
    <LoadError v-else-if="error" :message="error" @retry="load"/>
    <LoadingState v-else-if="loading" label="Loading the live scoreboard" detail="Checking every official MLB game currently in progress."/>
    <section v-else class="panel empty"><span class="ring"></span><h2>No MLB games are live right now</h2><p>The board refreshes every 10 seconds while this tab is visible.</p><RouterLink to="/schedule">VIEW TODAY'S SCHEDULE →</RouterLink></section>
  </div>
</template>

<style scoped>
.live-center{display:grid;gap:14px}.hero{padding:25px;display:flex;align-items:center;justify-content:space-between;gap:24px;background:radial-gradient(circle at 85%,rgba(255,32,110,.16),transparent 35%),var(--panel)}.hero .eyebrow{display:flex;align-items:center;gap:8px}.hero h1{font-size:34px;margin:7px 0}.hero p{font-size:11px;color:var(--muted);margin:0}.summary{min-width:130px;text-align:right;display:flex;flex-direction:column}.summary strong{font-size:36px;color:var(--acid)}.summary span{font-size:9px;font-weight:800}.summary small{font-size:8px;color:var(--muted);margin-top:6px}.game-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.empty{padding:60px 25px;text-align:center}.empty h2{font-size:18px;margin:14px 0 7px}.empty p{font-size:11px;color:var(--muted)}.empty a{display:inline-block;margin-top:13px;color:var(--acid);font-size:10px;font-weight:800;text-decoration:none}.ring{width:22px;height:22px;border:2px solid var(--orange);border-radius:50%;display:inline-block;box-shadow:0 0 16px rgba(255,32,110,.45)}@media(max-width:850px){.game-grid{grid-template-columns:1fr}}@media(max-width:520px){.hero{padding:18px;align-items:flex-start}.hero h1{font-size:27px}.summary strong{font-size:28px}.summary{min-width:80px}}
.hero{padding:31px;background:radial-gradient(circle at 85%,color-mix(in srgb,var(--orange) 13%,transparent),transparent 35%),var(--panel)}.hero h1{font-size:42px;line-height:.98;letter-spacing:-.055em;margin:11px 0}.hero h1 em{font-style:normal;color:var(--acid)}.summary strong{font-size:48px}
</style>
