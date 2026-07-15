<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search } from 'lucide-vue-next'
import { api } from '../services/api'
import SectionCard from '../components/ui/SectionCard.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import PlayerHeadshot from '../components/player/PlayerHeadshot.vue'
import ContextBack from '../components/navigation/ContextBack.vue'
import LoadingState from '../components/ui/LoadingState.vue'

const route = useRoute()
const router = useRouter()
const query = ref(String(route.query.q || ''))
const results = ref({ Teams: [], Players: [], Games: [] })
const loading = ref(false)
const error = ref('')
const total = computed(() => Object.values(results.value).reduce((sum, items) => sum + items.length, 0))

const submit = () => router.push({ path: '/search', query: query.value.trim() ? { q: query.value.trim() } : {} })
watch(() => route.query.q, async value => {
  query.value = String(value || '')
  error.value = ''
  if (query.value.trim().length < 2) { results.value = { Teams: [], Players: [], Games: [] }; return }
  loading.value = true
  try { results.value = await api.search(query.value.trim()) }
  catch { results.value = { Teams: [], Players: [], Games: [] }; error.value = 'Official MLB search is temporarily unavailable.' }
  finally { loading.value = false }
}, { immediate: true })
</script>

<template>
  <div class="search-page">
    <ContextBack fallback="/"/>
    <section class="panel head">
      <span class="eyebrow">NINTH / GLOBAL SEARCH</span>
      <h1>Find anyone in baseball.</h1>
      <p>Search active MLB players, all 30 clubs, and official games around today.</p>
      <form @submit.prevent="submit"><Search :size="18"/><input v-model="query" autofocus placeholder="Team, player, stadium, or matchup" aria-label="Search MLB"><button>SEARCH</button></form>
      <small v-if="route.query.q && !loading && !error">{{ total }} result{{ total === 1 ? '' : 's' }} for “{{ route.query.q }}”</small>
    </section>

    <LoadingState v-if="loading" compact label="Searching official MLB data" detail="Looking across teams, players and games."/>
    <div v-else-if="error" class="status error">{{ error }}</div>
    <template v-else-if="route.query.q">
      <SectionCard v-for="(items, group) in results" :key="group" :title="group" :subtitle="`${items.length} matching ${group.toLowerCase()}`">
        <div v-if="items.length" class="result-grid">
          <RouterLink v-for="item in items" :key="item.path" :to="item.path" class="result">
            <TeamLogo v-if="group === 'Teams'" :team="item" :size="50"/>
            <PlayerHeadshot v-else-if="group === 'Players'" :id="item.id" :name="item.name" :size="50"/>
            <span v-else class="game-mark">{{ item.abbr }}</span>
            <div><b>{{ item.name }}</b><small>{{ item.detail }}</small></div><i>OPEN →</i>
          </RouterLink>
        </div>
        <div v-else class="empty">No matching {{ group.toLowerCase() }} in the current official data.</div>
      </SectionCard>
    </template>
    <div v-else class="status">ENTER AT LEAST TWO CHARACTERS TO SEARCH</div>
  </div>
</template>

<style scoped>
.search-page{display:grid;gap:14px;padding-top:20px}.head{padding:34px}.head h1{font-size:clamp(32px,4vw,58px);letter-spacing:-.055em;line-height:.98;margin:14px 0 10px}.head p{font-size:11px;color:var(--muted);margin:0}.head form{max-width:720px;height:58px;margin-top:28px;display:flex;align-items:center;gap:13px;border-bottom:2px solid var(--ink)}.head input{min-width:0;flex:1;border:0;outline:0;background:transparent;font-size:16px;color:var(--text)}.head button{align-self:stretch;padding:0 22px;border:0;background:var(--ink);color:var(--paper);font:700 8px 'DM Mono';letter-spacing:.1em;cursor:pointer}.head>small{display:block;margin-top:12px;font:500 8px 'DM Mono';color:var(--muted)}.result-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.result{min-width:0;display:flex;align-items:center;gap:12px;padding:11px;border:1px solid var(--line);text-decoration:none}.result:hover{border-color:var(--ink);background:var(--accent)}.result>div{min-width:0;display:flex;flex:1;flex-direction:column}.result b,.result small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.result b{font-size:11px}.result small{font-size:8px;color:var(--muted);margin-top:4px}.result i{font:600 7px 'DM Mono';font-style:normal;color:var(--muted)}.game-mark{width:74px;height:50px;display:grid;place-items:center;text-align:center;background:var(--wash);font:700 8px 'DM Mono';line-height:1.4}.empty,.status{padding:28px;border:1px solid var(--line);background:var(--surface);font:500 9px 'DM Mono';color:var(--muted)}.status.error{color:#9c3329}
@media(max-width:700px){.search-page{padding-top:12px}.head{padding:24px 18px}.head form{height:50px}.head button{padding:0 14px}.result-grid{grid-template-columns:1fr}}
</style>
