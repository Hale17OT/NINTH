<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, CalendarDays, Database, Search, ShieldCheck, UsersRound } from 'lucide-vue-next'
import { sportById } from '../config/sports'
import { esportsDisciplines, workspaceData } from '../config/sportWorkspaces'
import { api } from '../services/api'
import { useRoute } from 'vue-router'

const props = defineProps({ sport: { type: String, required: true }, type: { type: String, required: true } })
const active = computed(() => sportById(props.sport))
const route = useRoute()
const catalog = computed(() => workspaceData[props.sport])
const query = ref('')
const competition = ref(String(route.query.competition || 'all'))
const discipline = ref('all')
const payload = ref(null)
const loading = ref(true)
const error = ref('')
const limit = ref(96)
const labels = { leagues: 'Leagues', games: 'Games', teams: 'Teams', players: 'Players' }
const singular = computed(() => ({ leagues: 'competition', games: catalog.value.unit, teams: catalog.value.subject, players: catalog.value.person }[props.type]))
const columns = computed(() => catalog.value[props.type])
const Icon = computed(() => ({ leagues: Database, games: CalendarDays, teams: ShieldCheck, players: UsersRound }[props.type]))
const items = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return payload.value?.items || []
  return (payload.value?.items || []).filter(row => JSON.stringify(row).toLowerCase().includes(needle))
})
const visibleItems = computed(() => items.value.slice(0, limit.value))
const groupedLeagues = computed(() => Object.entries(items.value.reduce((groups,row) => {
  ;(groups[row.group || 'Competition'] ||= []).push(row); return groups
}, {})))
const percentage = value => value == null ? '—' : value
const teamSummary = row => row.statistics?.worldRank ? `WORLD #${row.statistics.worldRank}` : row.statistics?.rating ? `ELO ${row.statistics.rating}` : row.formed ? `${row.formed} FOUNDED` : 'ACTIVE TEAM'
const teamRecord = row => row.statistics?.played ? `${row.statistics.wins}-${row.statistics.losses} SERIES` : row.country || 'INTERNATIONAL'
const playerSummary = row => row.statistics?.rating ? `RATING ${Number(row.statistics.rating).toFixed(2)}` : row.number ? `#${row.number}` : 'ACTIVE ROSTER'
const playerDetail = row => row.statistics?.acs ? `ACS ${Number(row.statistics.acs).toFixed(0)}` : row.statistics?.maps ? `${row.statistics.maps} MAPS` : row.competition || '—'

const load = async () => {
  loading.value = true; error.value = ''
  try {
    payload.value = await api.sportDirectory(props.sport, props.type, { competition: competition.value, discipline: discipline.value })
  }
  catch (caught) { error.value = caught?.message || 'The sport data feed could not be loaded.' }
  finally { loading.value = false }
}
watch(() => [props.sport, props.type], () => { competition.value = 'all'; discipline.value = 'all'; limit.value = 96; load() })
watch([competition, discipline], () => { limit.value = 96; load() })
watch(query, () => { limit.value = 96 })
onMounted(load)
</script>

<template>
  <div class="directory" :style="{'--sport':active.accent}">
    <section class="directory-head">
      <div><span class="eyebrow">{{ active.short }} / {{ labels[type].toUpperCase() }}</span><h1>{{ labels[type] }}<i>.</i></h1></div>
      <p>Live presentation data for {{ active.name }}, separated from model training and stamped with its source coverage.</p>
      <b class="index">{{ active.numeral }}/{{ type === 'leagues' ? '00' : type === 'games' ? '01' : type === 'teams' ? '02' : '03' }}</b>
    </section>

    <section class="directory-tools">
      <label><Search :size="16"/><input v-model="query" :placeholder="`Find a ${singular}`"><span>{{ items.length }} RESULTS</span></label>
      <select v-if="type !== 'leagues'" v-model="competition"><option value="all">All competitions</option><option v-for="item in payload?.competitions || []" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <select v-if="sport === 'esports' && type !== 'leagues'" v-model="discipline"><option value="all">Valorant + CS2 + LoL</option><option v-for="item in esportsDisciplines" :key="item.id" :value="item.id">{{ item.name }}</option></select>
    </section>

    <section class="schema-grid"><article v-for="(column,index) in columns" :key="column"><small>0{{ index + 1 }}</small><b>{{ column }}</b><span>OPERATIONAL DATA FIELD</span></article></section>

    <section class="data-frame">
      <header><span>{{ labels[type].toUpperCase() }} INDEX</span><span>SOURCE / {{ payload?.source || 'CONNECTING' }}</span><em>{{ payload?.count || 0 }} LIVE ROWS</em></header>
      <div v-if="loading" class="state"><component :is="Icon" class="pulse"/><b>Loading {{ labels[type].toLowerCase() }}</b><p>Synchronizing the source-backed directory.</p></div>
      <div v-else-if="error" class="state error"><AlertTriangle/><b>Provider connection required</b><p>{{ error }}</p><RouterLink :to="`${active.route}/data`">OPEN DATA REQUIREMENTS</RouterLink></div>

      <div v-else-if="type === 'leagues'" class="league-groups">
        <section v-for="group in groupedLeagues" :key="group[0]"><header><span>{{ group[0] }}</span><b>{{ group[1].length }}</b></header><div><article v-for="row in group[1]" :key="row.id"><small>{{ row.code }}</small><h2>{{ row.name }}</h2><p>{{ row.country }}</p><RouterLink :to="{path:`${active.route}/games`,query:{competition:row.id}}">OPEN COMPETITION</RouterLink></article></div></section>
      </div>

      <div v-else-if="type === 'games'" class="game-list">
        <article v-for="row in visibleItems" :key="row.id"><div class="game-date"><strong>{{ row.date?.slice(5) || 'TBD' }}</strong><span>{{ row.time }}</span></div><div class="game-competition"><small>{{ row.competitionCode }} · {{ row.round }}</small><b>{{ row.competition }}</b></div><div class="matchup"><span><img v-if="row.away?.badge" :src="row.away.badge"><b>{{ row.away?.name }}</b><em>{{ percentage(row.away?.score) }}</em></span><span><img v-if="row.home?.badge" :src="row.home.badge"><b>{{ row.home?.name }}</b><em>{{ percentage(row.home?.score) }}</em></span></div><div v-if="row.prediction && sport === 'esports'" class="forecast"><small>{{ row.prediction.modelStatus }} · {{ row.prediction.model }}</small><span><b>PICK</b> {{ row.prediction.recommended }}</span><span><b>HOME</b> {{ (row.prediction.markets.home_win*100).toFixed(0) }}%</span><span><b>AWAY</b> {{ (row.prediction.markets.away_win*100).toFixed(0) }}%</span></div><div v-else-if="row.prediction && sport === 'football'" class="forecast"><small>SHADOW FORECAST · xG {{ row.prediction.expected_goals.home.toFixed(2) }}–{{ row.prediction.expected_goals.away.toFixed(2) }}</small><span><b>1</b> {{ (row.prediction.markets.home_win*100).toFixed(0) }}%</span><span><b>X</b> {{ (row.prediction.markets.draw*100).toFixed(0) }}%</span><span><b>2</b> {{ (row.prediction.markets.away_win*100).toFixed(0) }}%</span><span><b>O2.5</b> {{ (row.prediction.markets.over_2_5*100).toFixed(0) }}%</span><span><b>BTTS</b> {{ (row.prediction.markets.both_teams_score*100).toFixed(0) }}%</span></div><div v-else-if="row.prediction" class="forecast"><small>SHADOW FORECAST · TOTAL {{ row.prediction.total_line }}</small><span><b>HOME</b> {{ (row.prediction.markets.home_win*100).toFixed(0) }}%</span><span><b>AWAY</b> {{ (row.prediction.markets.away_win*100).toFixed(0) }}%</span><span><b>OVER</b> {{ (row.prediction.markets.over_total*100).toFixed(0) }}%</span><span><b>UNDER</b> {{ (row.prediction.markets.under_total*100).toFixed(0) }}%</span></div><div class="game-state"><b>{{ row.status }}</b><small>{{ row.venue }}</small></div></article>
      </div>

      <div v-else-if="type === 'teams'" class="entity-grid team-cards">
        <article v-for="row in visibleItems" :key="row.id"><div class="entity-image"><img v-if="row.badge" :src="row.badge" :alt="`${row.name} badge`"><b v-else>{{ row.code }}</b></div><small>{{ row.competition || row.country }}</small><h2>{{ row.name }}</h2><p>{{ row.venue }}</p><footer><span>{{ teamSummary(row) }}</span><em>{{ teamRecord(row) }}</em></footer></article>
      </div>

      <div v-else class="entity-grid player-cards">
        <article v-for="row in visibleItems" :key="row.id"><div class="player-image"><img v-if="row.image" :src="row.image" :alt="row.name"><b v-else>{{ row.name?.split(' ').map(value=>value[0]).slice(0,2).join('') }}</b></div><small>{{ row.team }}</small><h2>{{ row.name }}</h2><p>{{ row.position }} · {{ row.nationality }}</p><footer><span>{{ playerSummary(row) }}</span><em>{{ playerDetail(row) }}</em></footer></article>
      </div>

      <div v-if="!loading && !error && !items.length" class="state"><component :is="Icon"/><b>No matching {{ labels[type].toLowerCase() }}</b><p>Change the competition or search filter.</p></div>
      <button v-if="!loading && !error && type !== 'leagues' && visibleItems.length < items.length" class="show-more" @click="limit += 96">SHOW 96 MORE <span>{{ items.length - visibleItems.length }} REMAINING</span></button>
    </section>

    <section v-if="payload" class="integrity"><Database/><div><b>{{ payload.coverage }}</b><p>{{ payload.warning }} <span v-if="payload.limited">Premier League coverage is complete now; an optional free-account token fills the other top-five squads.</span></p></div><em>{{ payload.generatedAt ? new Date(payload.generatedAt).toLocaleString() : '' }}</em></section>
  </div>
</template>

<style scoped>
.directory{padding-bottom:60px}.directory-head{min-height:340px;display:grid;grid-template-columns:1fr 420px 110px;align-items:end;gap:35px;padding:55px 0 38px;border-bottom:1px solid var(--line)}h1{margin:14px 0 0;font-size:clamp(74px,10vw,150px);line-height:.76;letter-spacing:-.095em}h1 i{color:var(--sport);font-style:normal}.directory-head>p{margin:0 0 10px;color:var(--muted);font-size:13px;line-height:1.7}.index{align-self:start;justify-self:end;font:500 26px 'DM Mono';color:var(--sport)}.directory-tools{display:flex;gap:8px;padding:22px 0}.directory-tools label,.directory-tools select{height:48px;border:1px solid var(--line);background:var(--surface);color:var(--text)}.directory-tools label{flex:1;display:flex;align-items:center;gap:11px;padding:0 13px}.directory-tools label input{flex:1;border:0;outline:0;background:transparent;color:var(--text)}.directory-tools label span{font:700 6px 'DM Mono';color:var(--sport)}.directory-tools select{min-width:215px;padding:0 12px;font-size:9px}.schema-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}.schema-grid article{min-height:135px;padding:18px;display:flex;flex-direction:column;background:var(--surface)}.schema-grid small{font:700 8px 'DM Mono';color:var(--sport)}.schema-grid b{margin:auto 0 8px;font-size:15px}.schema-grid span{font:600 6px 'DM Mono';color:var(--muted)}.data-frame{margin-top:30px;border:1px solid var(--line)}.data-frame>header{min-height:42px;padding:0 14px;display:grid;grid-template-columns:1fr 1fr auto;align-items:center;background:var(--contrast);color:var(--on-contrast);font:600 7px 'DM Mono'}.data-frame>header em{font-style:normal;color:var(--sport)}.state{min-height:380px;padding:40px;display:grid;place-items:center;align-content:center;text-align:center;gap:10px;background:radial-gradient(circle at 50% 20%,color-mix(in srgb,var(--sport) 10%,transparent),transparent 45%),var(--surface)}.state svg{width:42px;height:42px;color:var(--sport)}.state b{font-size:23px}.state p{max-width:560px;margin:0;color:var(--muted);font-size:10px;line-height:1.7}.state a{margin-top:10px;padding:11px 14px;background:var(--contrast);color:var(--on-contrast);text-decoration:none;font:700 7px 'DM Mono'}.pulse{animation:pulseData 1.2s infinite}@keyframes pulseData{50%{opacity:.3}}.league-groups>section>header{height:55px;padding:0 17px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.league-groups>section>header span{font:700 8px 'DM Mono';color:var(--sport)}.league-groups>section>header b{font:700 10px 'DM Mono'}.league-groups>section>div{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line)}.league-groups article{min-height:210px;padding:20px;display:flex;flex-direction:column;background:var(--surface)}.league-groups article small{font:800 20px 'DM Mono';color:var(--sport)}.league-groups h2{margin:auto 0 6px;font-size:24px;letter-spacing:-.05em}.league-groups p{margin:0;color:var(--muted);font-size:9px}.league-groups button{width:max-content;margin-top:18px;padding:8px;border:1px solid var(--line);background:transparent;font:700 6px 'DM Mono';cursor:pointer}.game-list>article{min-height:95px;padding:14px;display:grid;grid-template-columns:75px 210px 1fr 170px;align-items:center;gap:18px;border-bottom:1px solid var(--line)}.game-date{display:grid}.game-date strong{font:700 19px 'DM Mono';color:var(--sport)}.game-date span,.game-competition small,.game-state small{font:600 7px 'DM Mono';color:var(--muted)}.game-competition{display:grid;gap:5px}.game-competition b{font-size:10px}.matchup{display:grid;gap:6px}.matchup>span{display:grid;grid-template-columns:24px 1fr auto;align-items:center;gap:8px}.matchup img{width:22px;height:22px;object-fit:contain}.matchup b{font-size:11px}.matchup em{font:800 14px 'DM Mono';font-style:normal}.game-state{display:grid;justify-items:end;gap:5px;text-align:right}.game-state b{font:700 7px 'DM Mono';color:var(--sport)}.entity-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line)}.entity-grid>article{min-height:285px;padding:20px;display:flex;flex-direction:column;background:var(--surface)}.entity-image{height:95px;display:grid;place-items:start}.entity-image img{width:78px;height:78px;object-fit:contain}.entity-image b,.player-image b{width:70px;height:70px;display:grid;place-items:center;background:var(--contrast);color:var(--sport);font:800 14px 'DM Mono'}.entity-grid article>small{font:600 7px 'DM Mono';color:var(--sport)}.entity-grid h2{margin:auto 0 6px;font-size:22px;letter-spacing:-.05em}.entity-grid p{margin:0;color:var(--muted);font-size:9px}.entity-grid footer{display:flex;justify-content:space-between;margin-top:18px;padding-top:12px;border-top:1px solid var(--line);font:600 6px 'DM Mono';color:var(--muted)}.player-image{height:120px;margin:-20px -20px 16px;overflow:hidden;background:var(--wash)}.player-image img{width:100%;height:100%;object-fit:contain;object-position:center bottom}.player-image b{margin:25px 20px}.integrity{display:grid;grid-template-columns:25px 1fr auto;gap:14px;margin-top:16px;padding:18px;border:1px solid var(--line)}.integrity svg{color:var(--sport)}.integrity b{font-size:11px}.integrity p{margin:4px 0 0;color:var(--muted);font-size:9px;line-height:1.5}.integrity em{font:600 6px 'DM Mono';font-style:normal;color:var(--muted)}@media(max-width:1050px){.directory-head{grid-template-columns:1fr}.directory-head>p{max-width:650px}.index{display:none}.entity-grid{grid-template-columns:repeat(3,1fr)}.game-list>article{grid-template-columns:65px 170px 1fr}.game-state{grid-column:3;justify-items:start;text-align:left}.league-groups>section>div{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){.directory-head{min-height:300px;padding-top:35px}.directory-tools{display:grid}.directory-tools select{width:100%}.schema-grid{grid-template-columns:repeat(2,1fr)}.schema-grid article{min-height:100px}.data-frame>header{grid-template-columns:1fr auto}.data-frame>header span:nth-child(2){display:none}.league-groups>section>div,.entity-grid{grid-template-columns:1fr 1fr}.game-list>article{grid-template-columns:55px 1fr}.game-competition{grid-column:2}.matchup{grid-column:1/-1}.game-state{grid-column:1/-1}.integrity{grid-template-columns:25px 1fr}.integrity em{grid-column:2}}@media(max-width:480px){.league-groups>section>div,.entity-grid{grid-template-columns:1fr}}
.league-groups article>a{width:max-content;margin-top:18px;padding:8px;border:1px solid var(--line);color:var(--text);text-decoration:none;font:700 6px 'DM Mono'}.game-list article:has(.forecast){grid-template-columns:75px 190px minmax(210px,1fr) minmax(310px,1.2fr) 120px}.forecast{display:grid;grid-template-columns:repeat(5,auto);gap:7px 12px;padding:9px 11px;border:1px solid var(--line);background:color-mix(in srgb,var(--sport) 8%,var(--surface));font:700 8px 'DM Mono'}.forecast small{grid-column:1/-1;color:var(--sport);font-size:6px}.forecast span{white-space:nowrap}.forecast span b{color:var(--muted);font-size:6px}@media(max-width:1150px){.game-list article:has(.forecast){grid-template-columns:65px 160px 1fr}.forecast{grid-column:2/-1}.game-list article:has(.forecast) .game-state{grid-column:2/-1}}@media(max-width:720px){.forecast{grid-column:1/-1;grid-template-columns:repeat(3,1fr)}}
.show-more{width:100%;min-height:58px;display:flex;align-items:center;justify-content:center;gap:12px;border:0;border-top:1px solid var(--line);background:var(--surface);color:var(--text);font:800 8px 'DM Mono';cursor:pointer}.show-more:hover{background:color-mix(in srgb,var(--sport) 8%,var(--surface))}.show-more span{color:var(--sport)}
.matchup b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>
