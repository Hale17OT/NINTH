<script setup>
import { ref, onBeforeUnmount, onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../services/api'
import BaseDiamond from '../components/game/BaseDiamond.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import LiveProjection from '../components/game/LiveProjection.vue'
import LiveGameStats from '../components/game/LiveGameStats.vue'
import ContextBack from '../components/navigation/ContextBack.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import LoadError from '../components/ui/LoadError.vue'
const data = ref()
const refreshing = ref(false)
const error = ref('')
const activeId = ref()
const gameStateLabel = computed(() => {
  const status=data.value?.game?.status||'',inning=data.value?.game?.inning||''
  return status.toLowerCase()===inning.toLowerCase()?status:`${status} · ${inning}`
})
const route = useRoute()
let refreshTimer
let pendingReload = false
const load = async () => {
  if (refreshing.value) { pendingReload = true; return }
  const id = activeId.value || route.params.id
  if (!id || !/^\d+$/.test(id)) return
  const started = Date.now()
  refreshing.value = true
  error.value = ''
  try { data.value = await api.live(id) }
  catch (caught) { error.value = caught?.message || 'The live game could not be loaded.' }
  finally {
    const remaining = 320 - (Date.now() - started)
    if (remaining > 0) await new Promise(resolve => window.setTimeout(resolve, remaining))
    refreshing.value = false
    if (pendingReload) { pendingReload = false; queueMicrotask(load) }
  }
}
onMounted(async () => {
  let id = route.params.id
  if (!id || !/^\d+$/.test(id)) id = (await api.games('today'))[0]?.id
  activeId.value = id
  if (id) await load()
  refreshTimer = window.setInterval(load, 5000)
})
onBeforeUnmount(() => window.clearInterval(refreshTimer))
watch(() => route.params.id, id => { if (id && /^\d+$/.test(id)) { activeId.value = id; load() } })
</script>
<template><div v-if="data" class="live">
  <ContextBack fallback="/live"/>
  <section class="score panel">
    <div class="score-team away"><div class="team-identity"><TeamLogo :team="data.game.away" :size="68"/><span><small>AWAY</small><b>{{ data.game.away.abbr }}</b></span></div><strong class="team-score mono">{{ data.game.away.score }}</strong></div>
    <div class="count"><span class="tag" :class="data.game.status==='In Progress'?'pink':''"><i v-if="data.game.status==='In Progress'" class="live-dot"></i>{{ gameStateLabel }}</span><p>BALLS <b>{{data.count.balls}}</b> STRIKES <b class="pink">{{data.count.strikes}}</b> OUTS <b>{{data.count.outs}}</b></p></div>
    <div class="score-team home"><strong class="team-score mono">{{ data.game.home.score }}</strong><div class="team-identity"><span><small>HOME</small><b>{{ data.game.home.abbr }}</b></span><TeamLogo :team="data.game.home" :size="68"/></div></div>
    <BaseDiamond :bases="data.game.bases"/>
  </section>
  <LiveProjection :game="data.game" :refreshing="refreshing"/>
  <LiveGameStats :stats="data.liveStats" :game="data.game" :current-pitcher-id="data.pitcher.id" :current-batter-id="data.batter.id"/>
  <SectionCard title="Official play-by-play"><div v-if="data.plays.length" class="plays"><article v-for="play in data.plays" :key="`${play.time}-${play.text}`"><i :class="play.type"></i><div><small>{{ play.time }} · {{ play.count }}</small><p>{{ play.text }}</p><b v-if="play.impact" class="pink">{{ play.impact }}</b></div></article></div><p v-else class="empty-live">No plays have been published for this game.</p></SectionCard>
</div><LoadError v-else-if="error" :message="error" @retry="load"/><LoadingState v-else label="Opening the live game" detail="Synchronizing score, game state, players and the latest projection."/></template>
<style scoped>
.live{display:grid;gap:14px}.score{padding:20px 30px;display:grid;grid-template-columns:minmax(220px,1fr) minmax(250px,.9fr) minmax(220px,1fr) auto;align-items:center;gap:26px}.score-team{min-width:0;display:flex;align-items:center;justify-content:space-between;gap:24px}.team-identity{min-width:0;display:flex;align-items:center;gap:13px}.team-identity>span{display:grid;min-width:45px}.score-team small{font-size:9px;color:var(--muted)}.score-team b{font-size:25px;line-height:1.1}.team-score{flex:none;min-width:54px;font-size:42px;line-height:1;text-align:center;color:var(--acid)}.score-team.home{text-align:right}.score-team.home .team-identity{justify-content:flex-end}.count{text-align:center}.count p{font:10px 'DM Mono';color:var(--muted)}.count p b{color:var(--acid);margin:0 8px}.plays article{display:flex;gap:12px;padding:0 0 18px;margin-bottom:15px;border-bottom:1px solid var(--line)}.plays i{width:10px;height:10px;border-radius:50%;background:var(--acid);margin-top:3px}.plays i.out{background:var(--orange)}.plays small{font:8px 'DM Mono';color:var(--muted)}.plays p{font-size:12px;line-height:1.55;margin:7px 0}.plays b{font-size:9px}@media(max-width:1000px){.score{grid-template-columns:1fr 1fr auto}.count{grid-column:1/-1;grid-row:2}.score>:last-child{grid-column:3;grid-row:1}}@media(max-width:650px){.score{padding:15px;grid-template-columns:1fr 1fr;gap:18px 12px}.score>:last-child{grid-column:1/-1;grid-row:3;margin:auto}.score-team{gap:10px}.team-identity{gap:7px}.score-team b{font-size:20px}.team-score{min-width:36px;font-size:32px}.team-identity :deep(.team-logo){width:54px!important;height:54px!important}.count p b{margin:0 4px}}
</style>
