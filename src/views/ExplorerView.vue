<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { api } from '../services/api'
import MetricCard from '../components/ui/MetricCard.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import TrendChart from '../components/charts/TrendChart.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
import CustomDatePicker from '../components/ui/CustomDatePicker.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { useRouter } from 'vue-router'

const props = defineProps({ type: String })
const router = useRouter()
const data = ref()
const loading = ref(false)
const error = ref('')
const date = ref(new Date().toISOString().slice(0, 10))
const team = ref('all')
let enrichmentTimer
let weatherPolls=0

const meta = computed(() => ({
  trends: ['League trends', 'Find the signal behind streaks, splits, and underlying performance.'],
  schedule: ['MLB schedule', 'Daily slate, probable pitchers, venues, and weather intelligence.'],
  injuries: ['Injuries & lineups', 'Official availability data when exposed by a configured provider.'],
  rankings: ['MLB rankings', 'Official records, scoring, run differential, splits, and standings.'],
}[props.type]))

const teamOptions = computed(() => {
  if (props.type !== 'schedule' || !Array.isArray(data.value)) return []
  const map = new Map()
  data.value.forEach(game => { map.set(game.away.id, game.away); map.set(game.home.id, game.home) })
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name))
})
const teamSelectOptions = computed(() => [{ value:'all', label:'All teams', meta:'MLB' }, ...teamOptions.value.map(item => ({ value:String(item.id), label:item.name, meta:item.abbr }))])

const filteredGames = computed(() => {
  if (!Array.isArray(data.value) || team.value === 'all') return data.value || []
  return data.value.filter(game => String(game.away.id) === team.value || String(game.home.id) === team.value)
})

const scheduleTitle = computed(() => {
  const label = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(new Date(`${date.value}T12:00:00Z`))
  const count = filteredGames.value.length
  return `${label} · ${count} ${count === 1 ? 'game' : 'games'}`
})
const scheduleDateDisplay = computed(() => {
  const value = new Date(`${date.value}T12:00:00Z`)
  return { day:new Intl.DateTimeFormat('en-US',{day:'2-digit',timeZone:'UTC'}).format(value), month:new Intl.DateTimeFormat('en-US',{month:'short',timeZone:'UTC'}).format(value).toUpperCase(), weekday:new Intl.DateTimeFormat('en-US',{weekday:'long',timeZone:'UTC'}).format(value).toUpperCase(), year:value.getUTCFullYear() }
})
const shiftDate = amount => { const value=new Date(`${date.value}T12:00:00Z`);value.setUTCDate(value.getUTCDate()+amount);date.value=value.toISOString().slice(0,10) }
const goToday = () => { date.value=new Date().toISOString().slice(0,10) }

async function load() {
  if (!data.value) loading.value = true
  error.value = ''
  try {
    data.value = props.type === 'trends' ? await api.trends()
      : props.type === 'injuries' ? await api.injuries()
      : props.type === 'rankings' ? await api.rankings()
      : await api.games('today', date.value)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
    window.clearTimeout(enrichmentTimer)
    if (props.type === 'schedule' && Array.isArray(data.value) && data.value.some(game => game.weatherPending) && weatherPolls < 5) { weatherPolls += 1; enrichmentTimer = window.setTimeout(load, 1800) }
  }
}

watch(date, () => { team.value = 'all'; weatherPolls = 0; data.value = undefined; load() })
onMounted(load)
onBeforeUnmount(() => window.clearTimeout(enrichmentTimer))
</script>

<template>
  <div class="explorer">
    <section class="title panel">
      <span class="eyebrow">NINTH / BASEBALL DECISION LAB</span>
      <h1>{{ meta[0] }}</h1><p>{{ meta[1] }}</p>
      <div v-if="type === 'schedule'" class="filters">
        <div class="date-focus"><button type="button" aria-label="Previous day" @click="shiftDate(-1)"><ChevronLeft/></button><div><small>{{scheduleDateDisplay.weekday}}</small><strong>{{scheduleDateDisplay.month}} {{scheduleDateDisplay.day}}, {{scheduleDateDisplay.year}}</strong></div><button type="button" aria-label="Next day" @click="shiftDate(1)"><ChevronRight/></button></div>
        <CustomDatePicker v-model="date" label="Choose date"/>
        <button type="button" class="today-button" @click="goToday">TODAY</button>
        <CustomSelect v-model="team" label="Team" :options="teamSelectOptions" searchable placeholder="All teams"/>
        <span class="source"><i></i> MLB-STATSAPI + OPEN-METEO</span>
      </div>
      <div v-else class="filters"><span class="source"><i></i>{{data?.source?.provider||data?.provider||'PROVIDER STATUS'}}</span></div>
    </section>

    <LoadingState v-if="loading" :label="type === 'schedule' ? 'Loading the official schedule' : 'Loading MLB intelligence'" detail="Synchronizing the selected date, teams and provider data."/>
    <div v-else-if="error" class="panel state error">{{ error }} <button @click="load">RETRY</button></div>

    <template v-else-if="type === 'schedule'">
      <SectionCard :title="scheduleTitle" subtitle="Times shown in US Eastern Time">
        <div v-if="filteredGames.length" class="table-wrap">
          <table class="data-table"><thead><tr><th>Time</th><th>Matchup</th><th>Probable starters</th><th>Venue</th><th>Weather</th><th>Status</th></tr></thead>
            <tbody><tr v-for="game in filteredGames" :key="game.id" class="game-row" tabindex="0" role="link" @click="router.push(`/games/${game.id}`)" @keydown.enter="router.push(`/games/${game.id}`)"><td class="mono">{{ game.time }}</td><td><div class="table-matchup"><TeamLogo :team="game.away" :size="30"/><b>{{ game.away.abbr }} @ {{ game.home.abbr }}</b><TeamLogo :team="game.home" :size="30"/></div></td><td>{{ game.pitchers.join(' / ') }}</td><td>{{ game.stadium }}</td><td><span class="teal">{{ game.weather }}</span><small v-if="game.weatherData">{{ game.weatherData.condition }} · {{ game.weatherData.precipitation }}% rain</small></td><td>{{ game.status }}</td></tr></tbody>
          </table>
        </div>
        <EmptyState v-else kind="games" :eyebrow="team === 'all' ? 'OFFICIAL SCHEDULE' : 'FILTERED SCHEDULE'" :title="team === 'all' ? 'No MLB games on this date' : 'No games for this team'" :detail="team === 'all' ? 'The official MLB schedule returned an empty slate. Use the date controls to check another day.' : 'This club is not scheduled on the selected date. Clear the team filter or choose another day.'"/>
      </SectionCard>
    </template>

    <template v-else-if="data?.unavailable"><section class="panel unavailable"><span class="eyebrow">{{data.provider}}</span><h2>{{data.title}} unavailable</h2><p>{{data.message}}</p></section></template>
    <template v-else-if="data">
      <div class="grid-auto"><MetricCard v-for="item in data.metrics" :key="item.label" v-bind="item" /></div>
      <div class="explore-grid"><SectionCard :title="data.featureTitle"><div v-for="item in data.features" :key="item.name" class="feature"><div><b>{{ item.name }}</b><small>{{ item.detail }}</small></div><strong class="mono" :class="item.tone || 'teal'">{{ item.value }}</strong><div class="progress"><i :style="{ width: `${item.score}%` }"></i></div></div></SectionCard><SectionCard title="Official data distribution"><TrendChart :values="data.chart" :labels="data.chartLabels" :type="data.chartType" :unit="data.chartUnit" :pink="type === 'injuries'" /><div class="insight"><b>◆ SOURCE NOTE</b><p>{{ data.insight }}</p></div></SectionCard></div>
      <SectionCard :title="data.tableTitle"><div class="table-wrap"><table class="data-table"><thead><tr><th v-for="heading in data.table.headers" :key="heading">{{ heading }}</th></tr></thead><tbody><tr v-for="(row, index) in data.table.rows" :key="index"><td v-for="(value, cell) in row" :key="cell" :class="cell ? 'mono' : ''">{{ value }}</td></tr></tbody></table></div></SectionCard>
    </template>
  </div>
</template>

<style scoped>
.explorer{display:grid;gap:14px}.title{padding:25px;background:radial-gradient(circle at 90%,rgba(255,32,110,.08),transparent 35%),var(--panel)}h1{font-size:32px;margin:7px 0}.title p{font-size:12px;color:var(--muted)}.filters{display:flex;gap:8px;margin-top:18px;align-items:end}.filters button,.filters input,.filters select{height:35px;padding:0 10px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:5px;font-size:10px}.filters label{display:flex;flex-direction:column;gap:5px}.filters label>span{font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}.source{margin-left:auto;font:9px 'DM Mono';color:var(--muted);padding-bottom:10px}.source i{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--acid);margin-right:6px}.state{padding:40px;text-align:center;font:11px 'DM Mono';color:var(--acid)}.state.error{color:var(--orange)}.state button{margin-left:12px}.unavailable{padding:40px;text-align:center}.unavailable h2{font-size:20px;margin:10px}.unavailable p{font-size:11px;color:var(--muted)}.explore-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:14px}.feature{display:grid;grid-template-columns:1fr auto;gap:7px;padding:12px 0;border-bottom:1px solid var(--line)}.feature div:first-child{display:flex;flex-direction:column}.feature small{font-size:9px;color:var(--muted);margin-top:4px}.feature strong{font-size:15px}.feature .progress{grid-column:1/-1}.insight{background:var(--raised);padding:13px;font-size:10px;line-height:1.6}.insight b{color:var(--acid)}.insight p{margin-bottom:0}.data-table a{text-decoration:none}.table-matchup{display:flex;align-items:center;gap:7px;white-space:nowrap}.data-table td small{display:block;color:var(--muted);font-size:8px;margin-top:3px}.empty{padding:35px;text-align:center;color:var(--muted);font-size:11px}
@media(max-width:750px){.explore-grid{grid-template-columns:1fr}.filters{overflow-x:auto;align-items:end}.filters>*{flex:none}.source{display:none}}
.explorer{grid-template-columns:minmax(0,1fr);min-width:0}.explorer>*{min-width:0}
.game-row{cursor:pointer;transition:.15s}.game-row:hover,.game-row:focus{background:var(--accent);outline:0}.game-row td:first-child{border-left:3px solid transparent}.game-row:hover td:first-child,.game-row:focus td:first-child{border-left-color:var(--ink)}
.date-focus{height:58px;display:grid;grid-template-columns:42px minmax(145px,auto) 42px;align-items:center;gap:0;margin-right:8px;border:1px solid var(--line);background:var(--surface)}.date-focus>button{width:42px;height:100%!important;display:grid;place-items:center;padding:0!important;border:0!important;border-radius:0!important;background:transparent!important;cursor:pointer}.date-focus>button:first-child{border-right:1px solid var(--line)!important}.date-focus>button:last-child{border-left:1px solid var(--line)!important}.date-focus>button:hover{background:var(--accent)!important}.date-focus>div{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 17px}.date-focus strong{font-size:15px;letter-spacing:-.02em}.date-focus small{font:600 7px 'DM Mono';letter-spacing:.1em;color:var(--orange);margin-bottom:4px}.today-button{height:44px!important;border-radius:0!important;background:var(--ink)!important;color:var(--paper)!important;font:600 8px 'DM Mono'!important;letter-spacing:.08em}.filters :deep(.custom-select),.filters :deep(.date-picker){min-width:205px}.filters{align-items:end}
@media(max-width:900px){.filters{flex-wrap:wrap;overflow:visible}.date-focus{width:100%;grid-template-columns:42px 1fr 42px;margin:0 0 4px}.filters :deep(.custom-select),.filters :deep(.date-picker){flex:1;min-width:190px}}
</style>
