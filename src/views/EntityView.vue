<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../services/api'
import ContextBack from '../components/navigation/ContextBack.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import LoadError from '../components/ui/LoadError.vue'
import MetricCard from '../components/ui/MetricCard.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
import TrendChart from '../components/charts/TrendChart.vue'
import AnalyticsChart from '../components/charts/AnalyticsChart.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import PlayerHeadshot from '../components/player/PlayerHeadshot.vue'
import PlayerPercentileProfile from '../components/analytics/PlayerPercentileProfile.vue'
import RollingTrend from '../components/analytics/RollingTrend.vue'
import SplitComparison from '../components/analytics/SplitComparison.vue'
import AdvancedMetricTable from '../components/analytics/AdvancedMetricTable.vue'
import ModelDriverPanel from '../components/analytics/ModelDriverPanel.vue'

const props = defineProps({ type: String })
const route = useRoute()
const data = ref()
const loading = ref(true)
const error = ref('')
const teamGameFilter = ref('all')
const activePlayerLogGroup = ref('')
const playerOpponentFilter = ref('all')
const playerVenueFilter = ref('all')
let loadToken = 0
const rosterGroups = ['Starting rotation', 'Bullpen', 'Starting lineup', 'Bench']
const groupedRoster = computed(() => Object.fromEntries(rosterGroups.map(group => [group, (data.value?.roster || []).filter(player => player.group === group)])))
const playerAnalytics = computed(() => data.value?.analytics || {})
const playerTrendSeries = computed(() => {
  const trends = playerAnalytics.value.trends || {}, rows = []
  if (trends.primary?.length) rows.push({ label: trends.primaryLabel || 'Primary output', values: trends.primary, color: '#d6ff61' })
  if (trends.secondary?.length) rows.push({ label: trends.secondaryLabel || 'Secondary output', values: trends.secondary, color: '#809fff', fill: false })
  return rows
})
const playerDrivers = computed(() => [...(playerAnalytics.value.metrics || [])].filter(row => row.percentile != null).sort((a,b)=>b.percentile-a.percentile).slice(0,3).map(row => ({ label: row.label, detail: `${row.percentile}th percentile · ${row.value}` })))
const playerGameLogs = computed(() => data.value?.gameLogs || [])
const activePlayerGameLog = computed(() => playerGameLogs.value.find(section => section.group === activePlayerLogGroup.value) || playerGameLogs.value[0] || null)
const playerOpponentOptions = computed(() => {
  const rows = activePlayerGameLog.value?.rows || [], opponents = new Map()
  rows.forEach(row => {
    if (!row.opponent_id) return
    const key = String(row.opponent_id), current = opponents.get(key) || { value:key, label:row.opponent || 'Unknown opponent', games:0 }
    current.games += 1
    opponents.set(key, current)
  })
  return [
    { value:'all', label:'All opponents', meta:`${rows.length} games` },
    ...[...opponents.values()].sort((left,right)=>left.label.localeCompare(right.label)).map(row => ({ ...row, meta:`${row.games} game${row.games===1?'':'s'}` })),
  ]
})
const filteredPlayerRows = computed(() => [...(activePlayerGameLog.value?.rows || [])].filter(row => {
  if (playerOpponentFilter.value !== 'all' && String(row.opponent_id) !== String(playerOpponentFilter.value)) return false
  if (playerVenueFilter.value === 'home' && !row.is_home) return false
  if (playerVenueFilter.value === 'away' && row.is_home) return false
  return true
}).sort((left,right) => String(right.date || '').localeCompare(String(left.date || '')) || Number(right.game_number || 0) - Number(left.game_number || 0) || Number(right.game_id || 0) - Number(left.game_id || 0)))
const selectedPlayerOpponent = computed(() => playerOpponentOptions.value.find(option => String(option.value) === String(playerOpponentFilter.value)))
const playerScopeLabel = computed(() => `${selectedPlayerOpponent.value?.label || 'All opponents'} · ${playerVenueFilter.value === 'home' ? 'Home' : playerVenueFilter.value === 'away' ? 'Away' : 'Home + away'} · ${filteredPlayerRows.value.length} game${filteredPlayerRows.value.length===1?'':'s'}`)
const numericStat = value => value === null || value === undefined || value === '' || typeof value === 'boolean' ? null : Number.isFinite(Number(value)) ? Number(value) : null
const inningsToOuts = value => {
  if (value === null || value === undefined || value === '') return 0
  const [whole='0', fraction='0'] = String(value).split('.')
  return Math.max(0, Number(whole) * 3 + Math.min(2, Number(fraction) || 0))
}
const baseballInnings = outs => `${Math.floor(outs / 3)}.${Math.round(outs % 3)}`
const averageValue = value => Number.isFinite(value) ? (Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(2)) : '—'
const playerAverageMetrics = computed(() => {
  const rows = filteredPlayerRows.value, games = rows.length
  if (!games) return []
  const total = key => rows.reduce((sum,row) => sum + (numericStat(row.stats?.[key]) || 0), 0)
  if (activePlayerGameLog.value?.group === 'pitching') {
    const outs = rows.reduce((sum,row)=>sum+inningsToOuts(row.stats?.inningsPitched),0), strikeouts = total('strikeOuts'), walks = total('baseOnBalls'), hits = total('hits'), earnedRuns = total('earnedRuns'), pitches = total('numberOfPitches'), starts = total('gamesStarted')
    return [
      { label:'Appearances', value:String(games), detail:`${starts} starts` },
      { label:'IP / appearance', value:(outs / 3 / games).toFixed(2), detail:`${baseballInnings(outs)} total IP` },
      { label:'K / appearance', value:(strikeouts / games).toFixed(2), detail:`${strikeouts} total K` },
      { label:'BB / appearance', value:(walks / games).toFixed(2), detail:`${walks} total BB` },
      { label:'ERA', value:outs ? (earnedRuns * 27 / outs).toFixed(2) : '—', detail:`${(earnedRuns / games).toFixed(2)} ER / game` },
      { label:'WHIP', value:outs ? ((hits + walks) * 3 / outs).toFixed(2) : '—', detail:`${(hits / games).toFixed(2)} H / game` },
      { label:'K / 9', value:outs ? (strikeouts * 27 / outs).toFixed(2) : '—', detail:`${walks ? (strikeouts / walks).toFixed(2) : '—'} K / BB` },
      { label:'Pitches / appearance', value:(pitches / games).toFixed(1), detail:`${pitches} total pitches` },
    ]
  }
  if (activePlayerGameLog.value?.group === 'hitting') {
    const pa=total('plateAppearances'), ab=total('atBats'), hits=total('hits'), walks=total('baseOnBalls'), hbp=total('hitByPitch'), sf=total('sacFlies'), tb=total('totalBases'), obpDen=ab+walks+hbp+sf, avg=ab?hits/ab:null, obp=obpDen?(hits+walks+hbp)/obpDen:null, slg=ab?tb/ab:null
    return [
      { label:'Games', value:String(games), detail:`${pa} plate appearances` },
      { label:'PA / game', value:(pa / games).toFixed(2), detail:`${ab} total AB` },
      { label:'Hits / game', value:(hits / games).toFixed(2), detail:`${hits} total hits` },
      { label:'TB / game', value:(tb / games).toFixed(2), detail:`${tb} total bases` },
      { label:'HR / game', value:(total('homeRuns') / games).toFixed(2), detail:`${total('homeRuns')} total HR` },
      { label:'RBI / game', value:(total('rbi') / games).toFixed(2), detail:`${total('rbi')} total RBI` },
      { label:'AVG', value:avg?.toFixed(3).replace(/^0/,'') || '—', detail:`${(total('strikeOuts') / games).toFixed(2)} K / game` },
      { label:'OPS', value:obp !== null && slg !== null ? (obp+slg).toFixed(3).replace(/^0/,'') : '—', detail:`${(walks / games).toFixed(2)} BB / game` },
    ]
  }
  return [
    { label:'Games', value:String(games), detail:'Filtered fielding appearances' },
    { label:'Innings / game', value:(rows.reduce((sum,row)=>sum+inningsToOuts(row.stats?.innings),0) / 3 / games).toFixed(2), detail:'Defensive innings' },
    { label:'Chances / game', value:(total('chances') / games).toFixed(2), detail:`${total('chances')} total chances` },
    { label:'Putouts / game', value:(total('putOuts') / games).toFixed(2), detail:`${total('putOuts')} total PO` },
    { label:'Assists / game', value:(total('assists') / games).toFixed(2), detail:`${total('assists')} total assists` },
    { label:'Errors / game', value:(total('errors') / games).toFixed(2), detail:`${total('errors')} total errors` },
  ]
})
const nonAverageRateStats = new Set(['avg','obp','slg','ops','era','whip','strikePercentage','pitchesPerInning','strikeoutWalkRatio','strikeoutsPer9Inn','walksPer9Inn','hitsPer9Inn','homeRunsPer9','runsScoredPer9','winPercentage','stolenBasePercentage','caughtStealingPercentage','fielding','babip','groundOutsToAirouts','atBatsPerHomeRun','summary'])
const playerPerGameAverages = computed(() => {
  const rows = filteredPlayerRows.value, games = rows.length
  if (!games) return []
  return (activePlayerGameLog.value?.columns || []).filter(column => !nonAverageRateStats.has(column.key)).map(column => {
    if (column.key === 'inningsPitched' || column.key === 'innings') {
      const outs = rows.reduce((sum,row)=>sum+inningsToOuts(row.stats?.[column.key]),0)
      return outs ? { ...column, value:(outs / 3 / games).toFixed(2) } : null
    }
    const values = rows.map(row=>numericStat(row.stats?.[column.key])).filter(value=>value !== null)
    return values.length ? { ...column, value:averageValue(values.reduce((sum,value)=>sum+value,0) / games) } : null
  }).filter(Boolean)
})
const selectPlayerLogGroup = group => {
  activePlayerLogGroup.value = group
  playerOpponentFilter.value = 'all'
  playerVenueFilter.value = 'all'
}
const teamRankingGroups = ['OFFENSE', 'RUN PREVENTION']
const teamRankingsFor = group => (data.value?.leagueRankings || []).filter(row => row.group === group)
const teamRankTone = row => row.rank <= 5 ? 'elite' : row.rank >= Math.max(26, Number(row.teams || 30) - 4) ? 'concern' : 'middle'
const teamRankBand = row => row.rank <= 5 ? 'MLB ELITE' : row.rank <= 10 ? 'TOP THIRD' : row.rank >= Math.max(26, Number(row.teams || 30) - 4) ? 'BOTTOM FIVE' : row.rank >= Math.ceil(Number(row.teams || 30) * 2 / 3) ? 'BOTTOM THIRD' : 'LEAGUE MIDDLE'
const filteredTeamSchedule = computed(() => (data.value?.schedule || []).filter(game => {
  if (teamGameFilter.value === 'completed') return game.is_final
  if (teamGameFilter.value === 'upcoming') return !game.is_final && !/postponed|cancelled|suspended/i.test(game.status || '')
  return true
}).sort((left,right) => String(right.datetime || right.date || '').localeCompare(String(left.datetime || left.date || '')) || Number(right.game_id || 0) - Number(left.game_id || 0)))
const inningDistribution = computed(() => data.value?.inningDistribution || {})
const inningSeries = computed(() => [
  { label: 'Runs scored', values: inningDistribution.value.scored_per_game || [], color: '#d6ff61' },
  { label: 'Runs allowed', values: inningDistribution.value.allowed_per_game || [], color: '#809fff' },
])
const shortDate = value => value ? new Date(`${value}T12:00:00Z`).toLocaleDateString([], { month:'short', day:'numeric' }) : '—'
const gameResultLabel = game => game.is_final ? `${game.result || '—'} ${game.team_score}–${game.opponent_score}` : game.status || 'Scheduled'
const playerResultLabel = row => row.group === 'pitching' ? row.decision || (row.team_win ? 'W' : 'L') : row.team_win ? 'W' : 'L'
const load = async () => {
  const token = ++loadToken
  loading.value = true
  error.value = ''
  try {
    const result = props.type === 'team' ? await api.team(route.params.id) : await api.player(route.params.id)
    if (token === loadToken) {
      data.value = result
      activePlayerLogGroup.value = result.gameLogs?.[0]?.group || ''
      playerOpponentFilter.value = 'all'
      playerVenueFilter.value = 'all'
      teamGameFilter.value = 'all'
    }
  } catch (caught) {
    if (token === loadToken) { data.value = undefined; error.value = caught?.message || 'This profile could not be loaded.' }
  } finally {
    if (token === loadToken) loading.value = false
  }
}
onMounted(load)
watch(() => route.params.id, load)
</script>

<template>
  <div v-if="data" class="entity">
    <ContextBack :fallback="type === 'team' ? '/teams' : '/players'"/>
    <section class="profile">
      <div class="identity"><TeamLogo v-if="type==='team'" :team="{id:data.teamId,abbr:data.abbr,name:data.name}" :size="122"/><PlayerHeadshot v-else :id="data.playerId" :name="data.name" :size="126"/><div><span class="eyebrow">{{ data.kicker }}</span><h1>{{ data.name }}</h1><p>{{ data.subtitle }}</p></div></div>
      <div class="profile-side"><small>{{ data.highlightLabel }}</small><b class="mono">{{ data.highlight }}</b></div>
    </section>
    <div class="grid-auto" :class="{'team-metric-grid':type==='team'}"><MetricCard v-for="metric in data.metrics" :key="metric.label" v-bind="metric"/></div>
    <div class="entity-grid"><SectionCard :title="data.chartTitle"><TrendChart :values="data.chart" :labels="data.chartLabels" :type="data.chartType" :unit="data.chartUnit"/><div class="note"><b>SOURCE NOTE</b>{{ data.insight }}</div></SectionCard><SectionCard :title="data.rankingTitle"><div v-for="item in data.ranks" :key="item.label" class="rank"><div><b>{{ item.label }}</b><strong class="mono">{{ item.value }}</strong></div><div class="progress"><i :style="{width:`${item.score}%`}"></i></div><small>{{ item.note }}</small></div></SectionCard></div>

    <template v-if="type === 'player'">
      <ModelDriverPanel title="What the current profile says" :text="playerAnalytics.interpretation" :drivers="playerDrivers"/>
      <div v-if="playerTrendSeries.length" class="player-intelligence-grid"><RollingTrend :labels="playerAnalytics.trends?.labels||[]" :series="playerTrendSeries" title="Game-by-game production" :height="340"><p class="trend-note">Official chronological game-log observations; missing games are not imputed.</p></RollingTrend><SplitComparison :rows="playerAnalytics.splits||[]" title="Latest form versus full log"/></div>
      <PlayerPercentileProfile :metrics="playerAnalytics.metrics||[]" :sample="playerAnalytics.peerSample||0" :title="`${playerAnalytics.positionGroup||'MLB'} peer profile`"/>
      <AdvancedMetricTable :metrics="playerAnalytics.metrics||[]" :source="playerAnalytics.source" title="Rate definitions and context"/>
      <SectionCard v-if="playerGameLogs.length" :title="`Complete ${data.season || 2026} game log`" :subtitle="`${data.gameLogCount || 0} unique games · every official per-game stat returned by MLB`">
        <div class="log-toolbar"><div role="group" aria-label="Player game log type"><button v-for="section in playerGameLogs" :key="section.group" :class="{active:activePlayerGameLog?.group===section.group}" @click="selectPlayerLogGroup(section.group)">{{ section.label.toUpperCase() }} · {{ section.rows.length }}</button></div><span>NEWEST FIRST · CLICK A DATE, TEAM OR OPPONENT TO OPEN IT</span></div>
        <div class="player-log-filters">
          <CustomSelect v-model="playerOpponentFilter" label="Opponent" :options="playerOpponentOptions" searchable/>
          <div class="venue-filter"><span>LOCATION</span><div role="group" aria-label="Player game location"><button v-for="venue in [{value:'all',label:'BOTH'},{value:'home',label:'HOME'},{value:'away',label:'AWAY'}]" :key="venue.value" :class="{active:playerVenueFilter===venue.value}" @click="playerVenueFilter=venue.value">{{ venue.label }}</button></div></div>
          <div class="filter-scope"><small>CURRENT SAMPLE</small><b>{{ playerScopeLabel }}</b><RouterLink v-if="playerOpponentFilter!=='all'" :to="`/teams/${playerOpponentFilter}`">OPEN TEAM PAGE →</RouterLink></div>
        </div>
        <section v-if="filteredPlayerRows.length" class="player-average-panel">
          <header><div><span class="eyebrow">FILTERED PERFORMANCE</span><h3>Averages for this selection</h3></div><b class="mono">{{ filteredPlayerRows.length }} GAME{{ filteredPlayerRows.length===1?'':'S' }}</b></header>
          <div class="player-average-grid"><article v-for="metric in playerAverageMetrics" :key="metric.label"><small>{{ metric.label }}</small><strong class="mono">{{ metric.value }}</strong><span>{{ metric.detail }}</span></article></div>
          <div class="all-average-head"><div><b>ALL COUNTABLE STATS · PER-GAME AVERAGE</b><small>Rate fields such as ERA, WHIP, AVG and OPS are recomputed from the filtered totals above rather than averaged incorrectly.</small></div><span class="mono">{{ playerPerGameAverages.length }} FIELDS</span></div>
          <div class="table-wrap average-table-wrap"><table class="data-table average-table"><thead><tr><th v-for="column in playerPerGameAverages" :key="column.key">{{ column.label }}</th></tr></thead><tbody><tr><td v-for="column in playerPerGameAverages" :key="column.key" class="mono">{{ column.value }}</td></tr></tbody></table></div>
        </section>
        <p v-else class="empty-log">No {{ activePlayerGameLog?.label?.toLowerCase() || 'game log' }} entries match this opponent and location.</p>
        <div v-if="activePlayerGameLog && filteredPlayerRows.length" class="table-wrap full-log-wrap"><table class="data-table game-log-table"><thead><tr><th>Date</th><th>Team</th><th>Matchup</th><th>Result</th><th>Pos</th><th v-for="column in activePlayerGameLog.columns" :key="column.key">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in filteredPlayerRows" :key="`${row.group}-${row.game_id}-${row.positions?.join('-')}-${rowIndex}`"><td><RouterLink :to="`/games/${row.game_id}`">{{ shortDate(row.date) }}</RouterLink></td><td><RouterLink v-if="row.team_id" :to="`/teams/${row.team_id}`">{{ row.team || 'Team' }}</RouterLink><span v-else>{{ row.team || '—' }}</span></td><td><RouterLink v-if="row.opponent_id" :to="`/teams/${row.opponent_id}`">{{ row.is_home ? 'vs' : '@' }} {{ row.opponent }}</RouterLink><span v-else>{{ row.is_home ? 'vs' : '@' }} {{ row.opponent }}</span></td><td><b class="result-pill" :class="row.team_win?'win':'loss'">{{ playerResultLabel(row) }}</b></td><td class="mono">{{ row.positions?.join('/') || '—' }}</td><td v-for="column in activePlayerGameLog.columns" :key="column.key" class="mono">{{ row.stats?.[column.key] ?? '—' }}</td></tr></tbody></table></div>
      </SectionCard>
    </template>

    <template v-if="type === 'team'">
      <section class="team-season-strip">
        <span><small>ACTIVE SCHEDULE</small><b class="mono">{{ data.scheduleSummary?.active || 0 }}</b></span><span><small>COMPLETED</small><b class="mono">{{ data.scheduleSummary?.completed || 0 }}</b></span><span><small>UPCOMING</small><b class="mono">{{ data.scheduleSummary?.upcoming || 0 }}</b></span><span><small>POSTPONED / CANCELLED</small><b class="mono">{{ data.scheduleSummary?.postponed || 0 }}</b></span><span><small>RANKS THROUGH</small><b class="mono">{{ data.through || '—' }}</b></span>
      </section>
      <SectionCard title="MLB league standing by metric" :subtitle="`Current season rates ranked against all ${data.leagueTeamCount || 30} clubs · lower hitter K rate, ERA, WHIP and run allowance are better`">
        <div v-if="data.leagueRankings?.length" class="team-rank-groups">
          <section v-for="group in teamRankingGroups" :key="group"><header><span class="eyebrow">{{ group }}</span><b>{{ teamRankingsFor(group).length }} RANKED METRICS</b></header><div class="team-rank-grid"><article v-for="row in teamRankingsFor(group)" :key="row.key" :class="teamRankTone(row)"><span><small>{{ row.label }}</small><b class="mono">{{ row.display }}</b></span><i><em :style="{width:`${Math.max(4,row.percentile)}%`}"></em></i><strong class="mono">#{{ row.rank }}<small>{{ teamRankBand(row) }}</small></strong></article></div></section>
        </div><p v-else class="state">League-ranked team rates are temporarily unavailable.</p>
      </SectionCard>
      <SectionCard title="Run distribution by inning" :subtitle="`${inningDistribution.sample_games || 0} completed regular-season games · scoring and prevention shown per team game`">
        <div v-if="inningDistribution.available" class="team-innings"><AnalyticsChart type="bar" :labels="inningDistribution.labels||[]" :series="inningSeries" :height="330" unit="runs / game" begin-at-zero/><div><span v-for="phase in inningDistribution.phases?.filter(row=>row.label!=='EXTRAS')" :key="phase.label"><small>{{ phase.label }} · INN {{ phase.innings }}</small><b class="mono">{{ phase.scored_per_game }} FOR / {{ phase.allowed_per_game }} AGAINST</b><em>{{ phase.scored_share }}% of offense · {{ phase.allowed_share }}% allowed</em></span></div></div><p v-else class="state">Inning-level team distributions are temporarily unavailable.</p>
      </SectionCard>
      <SectionCard :title="`Complete ${data.season || 2026} schedule and results`" subtitle="Regular season and postseason · every official game currently returned by MLB">
        <div class="schedule-toolbar"><div role="group" aria-label="Team game filter"><button v-for="filter in ['all','completed','upcoming']" :key="filter" :class="{active:teamGameFilter===filter}" @click="teamGameFilter=filter">{{ filter.toUpperCase() }}</button></div><span>{{ filteredTeamSchedule.length }} ENTRIES · MOST RECENT FIRST</span></div>
        <div class="table-wrap team-schedule-wrap"><table class="data-table team-schedule"><thead><tr><th>Date</th><th>Opponent</th><th>Site</th><th>Result / status</th><th>Starting pitchers</th><th>Venue</th><th>Series</th></tr></thead><tbody><tr v-for="game in filteredTeamSchedule" :key="game.game_id"><td><RouterLink :to="`/games/${game.game_id}`">{{ shortDate(game.date) }}</RouterLink></td><td><RouterLink :to="`/teams/${game.opponent_id}`">{{ game.opponent }}</RouterLink></td><td class="mono">{{ game.is_home ? 'HOME' : 'AWAY' }}</td><td><b class="schedule-result" :class="game.result==='W'?'win':game.result==='L'?'loss':'pending'">{{ gameResultLabel(game) }}</b></td><td><span class="starter-links"><RouterLink v-if="game.team_starter_id" :to="`/players/${game.team_starter_id}`">{{ game.team_starter }}</RouterLink><span v-else>TBD</span><em>vs</em><RouterLink v-if="game.opponent_starter_id" :to="`/players/${game.opponent_starter_id}`">{{ game.opponent_starter }}</RouterLink><span v-else>TBD</span></span></td><td>{{ game.venue || '—' }}</td><td>{{ game.series || '—' }}</td></tr></tbody></table></div>
      </SectionCard>
      <SectionCard title="Complete active roster" subtitle="Roles are grouped from official active-roster positions and current-season usage">
        <div class="roster-groups">
          <section v-for="group in rosterGroups" :key="group" v-show="groupedRoster[group]?.length" class="roster-group">
            <header><span class="eyebrow">{{ group }}</span><b class="mono">{{ groupedRoster[group]?.length }}</b></header>
            <div class="roster-grid">
              <RouterLink v-for="player in groupedRoster[group]" :key="player.id" :to="{path:`/players/${player.id}`,query:{from:`/teams/${data.teamId}`}}" class="roster-card" :class="`role-${group.toLowerCase().replaceAll(' ','-')}`">
                <PlayerHeadshot :id="player.id" :name="player.name" :size="112"/>
                <div><span class="role">{{ player.role }}</span><h3>{{ player.name }}</h3><p>#{{ player.number }} · {{ player.positionName }}</p><small v-if="player.starts">{{ player.starts }} starts · {{ player.innings || '—' }} IP</small><small v-else>{{ player.games }} games<span v-if="player.ops"> · {{ player.ops }} OPS</span></small></div>
              </RouterLink>
            </div>
          </section>
        </div>
      </SectionCard>
      <SectionCard :title="data.statusTitle"><div v-for="item in data.status" :key="item.name" class="status"><div><b>{{ item.name }}</b><small>{{ item.detail }}</small></div><strong class="mono" :class="item.tone">{{ item.value }}</strong></div></SectionCard>
    </template>

    <div v-else class="entity-grid"><SectionCard :title="data.leaderTitle"><div class="leaders"><article v-for="person in data.leaders" :key="person.name"><PlayerHeadshot class="portrait" :id="person.id" :name="person.name" :size="140"/><h3>{{ person.name }}</h3><p>{{ person.role }}</p><div><span v-for="(value,key) in person.stats" :key="key"><small>{{ key }}</small><b class="mono">{{ value }}</b></span></div></article></div></SectionCard><SectionCard :title="data.statusTitle"><div v-for="item in data.status" :key="item.name" class="status"><div><b>{{ item.name }}</b><small>{{ item.detail }}</small></div><strong class="mono" :class="item.tone">{{ item.value }}</strong></div></SectionCard></div>
    <SectionCard :title="data.tableTitle"><div class="table-wrap"><table class="data-table"><thead><tr><th v-for="heading in data.table.headers" :key="heading">{{ heading }}</th></tr></thead><tbody><tr v-for="(row,index) in data.table.rows" :key="index"><td v-for="(value,cell) in row" :key="cell" :class="cell?'mono':''">{{ value }}</td></tr></tbody></table></div></SectionCard>
  </div>
  <LoadError v-else-if="error" :message="error" @retry="load"/>
  <LoadingState v-else-if="loading" :label="type === 'team' ? 'Loading team room' : 'Loading player profile'" detail="Synchronizing the latest official roster and season statistics."/>
</template>

<style scoped>
.player-intelligence-grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(280px,.7fr);gap:11px}.trend-note{margin:10px 0 0;color:var(--muted);font-size:8px;line-height:1.5}
.entity{display:grid;gap:11px;padding-top:20px}.back{display:flex;align-items:center;gap:6px;width:max-content;padding:8px 0;text-decoration:none;font:600 8px 'DM Mono';color:var(--muted)}.profile{min-height:260px;padding:32px 0;display:flex;align-items:center;gap:30px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.identity{display:flex;align-items:center;gap:24px}.identity>div{min-width:0}h1{font-size:clamp(38px,6vw,78px);line-height:.9;letter-spacing:-.075em;margin:13px 0 18px}.profile p{font:9px 'DM Mono';color:var(--muted)}.profile-side{margin-left:auto;min-width:180px;height:150px;background:var(--ink);color:var(--paper);display:flex;flex-direction:column;justify-content:end;padding:20px}.profile-side small{font:500 8px 'DM Mono';color:#989d95}.profile-side b{font-size:36px;color:var(--accent);margin-top:8px}.entity-grid{display:grid;grid-template-columns:1.45fr 1fr;gap:11px}.note{border-left:3px solid var(--orange);padding:12px;margin-top:10px;font-size:10px;line-height:1.6;color:var(--muted)}.note b{display:block;font:600 7px 'DM Mono';color:var(--text);margin-bottom:5px}.rank{margin:17px 0}.rank>div{display:flex;justify-content:space-between;font-size:10px;margin-bottom:7px}.rank small{display:block;color:var(--muted);font:8px 'DM Mono';margin-top:6px}.leaders{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.leaders article{padding:12px;background:var(--wash);min-width:0}.portrait{height:140px;width:100%!important;background:var(--surface)}.leaders h3{margin:10px 0 2px;font-size:12px}.leaders p{font-size:8px;color:var(--muted);margin:0 0 10px}.leaders article>div:last-child{display:flex;gap:20px}.leaders span{display:flex;flex-direction:column}.leaders small{font-size:7px;color:var(--muted)}.leaders b{font-size:10px}.status{display:flex;align-items:center;gap:10px;border-top:1px solid var(--line);padding:13px 0}.status div{display:flex;flex-direction:column}.status small{font-size:8px;color:var(--muted);margin-top:3px}.status strong{margin-left:auto;font-size:11px}.roster-groups{display:grid;gap:28px}.roster-group>header{display:flex;align-items:center;justify-content:space-between;padding-bottom:9px;border-bottom:1px solid var(--ink)}.roster-group>header b{font-size:9px;color:var(--muted)}.roster-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}.roster-card{min-width:0;display:grid;grid-template-columns:112px 1fr;align-items:stretch;border:1px solid var(--line);background:var(--wash);text-decoration:none;overflow:hidden}.roster-card :deep(.headshot){border:0;border-right:1px solid var(--line);border-radius:0;width:112px!important;height:132px!important}.roster-card>div{min-width:0;padding:12px;display:flex;flex-direction:column}.roster-card .role{width:max-content;max-width:100%;padding:4px 6px;background:var(--ink);color:var(--accent);font:600 7px 'DM Mono';text-transform:uppercase}.roster-card h3{font-size:12px;margin:10px 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.roster-card p,.roster-card small{font-size:8px;color:var(--muted);margin:0}.roster-card small{margin-top:auto}.state{padding:90px;text-align:center;font:9px 'DM Mono'}
.roster-card{border-left:4px solid var(--role-color,#777)}.roster-card .role{background:var(--role-color,#777);color:#fff}.role-starting-rotation{--role-color:#d95436}.role-bullpen{--role-color:#276b9a}.role-starting-lineup{--role-color:#568900}.role-bench{--role-color:#686c66}.roster-group:nth-child(1)>header{border-color:#d95436}.roster-group:nth-child(2)>header{border-color:#276b9a}.roster-group:nth-child(3)>header{border-color:#568900}.roster-group:nth-child(4)>header{border-color:#686c66}
.team-metric-grid{grid-template-columns:repeat(6,minmax(0,1fr))}
.team-season-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}.team-season-strip>span{min-height:92px;padding:15px;background:var(--surface);display:flex;flex-direction:column;justify-content:end}.team-season-strip small{font:700 7px 'DM Mono';letter-spacing:.08em;color:var(--muted)}.team-season-strip b{margin-top:8px;font-size:21px}.team-rank-groups{display:grid;grid-template-columns:1fr 1fr;gap:16px}.team-rank-groups>section{min-width:0;padding:15px;border:1px solid var(--line);background:var(--wash)}.team-rank-groups>section>header{display:flex;align-items:center;justify-content:space-between;padding-bottom:11px;border-bottom:1px solid var(--line)}.team-rank-groups>section>header b{font:700 7px 'DM Mono';color:var(--muted)}.team-rank-grid{display:grid;gap:1px;margin-top:1px}.team-rank-grid article{display:grid;grid-template-columns:minmax(150px,1fr) minmax(55px,.65fr) 76px;gap:10px;align-items:center;min-height:58px;border-bottom:1px solid var(--line)}.team-rank-grid article>span{display:grid;gap:4px}.team-rank-grid article>span small{font-size:8px;color:var(--muted)}.team-rank-grid article>span b{font-size:14px}.team-rank-grid article>i{height:5px;background:var(--panel);overflow:hidden;border-radius:99px}.team-rank-grid article>i em{display:block;height:100%;background:var(--blue);border-radius:99px}.team-rank-grid article>strong{display:grid;justify-items:end;font-size:18px}.team-rank-grid article>strong small{margin-top:4px;font:700 6px 'DM Mono';color:var(--muted)}.team-rank-grid article.elite>strong,.team-rank-grid article.elite>strong small{color:var(--acid)}.team-rank-grid article.concern>strong,.team-rank-grid article.concern>strong small{color:var(--orange)}.team-innings{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,.65fr);gap:16px}.team-innings>div:last-child{display:grid;gap:6px}.team-innings>div:last-child span{padding:13px;background:var(--wash);display:grid;gap:5px}.team-innings small{font:700 7px 'DM Mono';color:var(--muted)}.team-innings b{font-size:11px}.team-innings em{font-size:8px;font-style:normal;color:var(--muted)}.log-toolbar,.schedule-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:12px}.log-toolbar>div,.schedule-toolbar>div{display:flex;flex-wrap:wrap;gap:5px}.log-toolbar button,.schedule-toolbar button{padding:9px 12px;border:1px solid var(--line);background:var(--wash);color:var(--muted);font:800 7px 'DM Mono'}.log-toolbar button.active,.schedule-toolbar button.active{background:var(--ink);color:var(--accent);border-color:var(--ink)}.log-toolbar>span,.schedule-toolbar>span{font:700 7px 'DM Mono';color:var(--muted)}.full-log-wrap,.team-schedule-wrap{max-height:720px;border:1px solid var(--line)}.game-log-table,.team-schedule{min-width:1280px}.game-log-table th,.game-log-table td,.team-schedule th,.team-schedule td{white-space:nowrap}.game-log-table a,.team-schedule a{color:var(--text);font-weight:800;text-decoration-color:color-mix(in srgb,var(--accent) 60%,transparent);text-underline-offset:3px}.result-pill,.schedule-result{display:inline-grid;place-items:center;min-width:34px;padding:5px 7px;background:var(--wash);font:800 8px 'DM Mono'}.result-pill.win,.schedule-result.win{color:#11845b;background:color-mix(in srgb,#11845b 10%,var(--surface))}.result-pill.loss,.schedule-result.loss{color:var(--orange);background:color-mix(in srgb,var(--orange) 10%,var(--surface))}.schedule-result.pending{color:var(--muted)}.starter-links{display:flex;align-items:center;gap:6px}.starter-links em{font:700 7px 'DM Mono';font-style:normal;color:var(--muted)}
.player-log-filters{display:grid;grid-template-columns:minmax(240px,.7fr) minmax(300px,.8fr) minmax(300px,1.4fr);gap:10px;align-items:end;margin:18px 0}.player-log-filters :deep(.custom-select){width:100%;min-width:0}.venue-filter>span{display:block;margin-bottom:8px;color:var(--muted);font:600 12px 'DM Mono';letter-spacing:.08em}.venue-filter>div{height:48px;display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line)}.venue-filter button{border:0;border-right:1px solid var(--line);background:var(--surface);color:var(--muted);font:800 8px 'DM Mono'}.venue-filter button:last-child{border-right:0}.venue-filter button.active{background:var(--ink);color:var(--accent)}.filter-scope{min-height:72px;padding:11px 14px;border-left:3px solid var(--accent);background:var(--wash);display:grid;align-content:center;gap:5px}.filter-scope small{font:700 7px 'DM Mono';color:var(--muted)}.filter-scope b{font-size:11px}.filter-scope a{width:max-content;color:var(--accent);font:800 7px 'DM Mono';text-decoration:none}.player-average-panel{margin-bottom:12px;padding:16px;border:1px solid var(--line);background:var(--wash)}.player-average-panel>header{display:flex;align-items:end;justify-content:space-between;gap:16px;padding-bottom:13px;border-bottom:1px solid var(--line)}.player-average-panel h3{margin:6px 0 0;font-size:20px}.player-average-panel>header>b{font-size:10px;color:var(--accent)}.player-average-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;margin-top:12px;background:var(--line);border:1px solid var(--line)}.player-average-grid article{min-height:102px;padding:14px;background:var(--surface);display:flex;flex-direction:column;justify-content:end}.player-average-grid small{font:700 7px 'DM Mono';color:var(--muted);text-transform:uppercase}.player-average-grid strong{margin:7px 0 5px;font-size:23px;color:var(--accent)}.player-average-grid span{font-size:8px;color:var(--muted)}.all-average-head{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-top:16px}.all-average-head>div{display:grid;gap:4px}.all-average-head b,.all-average-head>span{font:800 8px 'DM Mono'}.all-average-head small{max-width:750px;color:var(--muted);font-size:8px;line-height:1.5}.average-table-wrap{margin-top:9px;border:1px solid var(--line)}.average-table{width:max-content;min-width:100%}.average-table th,.average-table td{min-width:82px;white-space:nowrap;text-align:center}.average-table tbody td{color:var(--accent);font-weight:800}.full-log-wrap{margin-top:12px}.empty-log{padding:42px 16px;border:1px dashed var(--line);color:var(--muted);text-align:center;font:700 9px 'DM Mono'}
@media(max-width:1100px){.roster-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:800px){.profile{align-items:flex-start;flex-wrap:wrap}.identity{align-items:flex-start}.profile-side{width:100%;height:110px;margin:0}.entity-grid{grid-template-columns:1fr}.leaders{grid-template-columns:1fr 1fr}}@media(max-width:600px){.roster-grid{grid-template-columns:1fr}.roster-card{grid-template-columns:96px 1fr}.roster-card :deep(.headshot){width:96px!important;height:118px!important}}@media(max-width:520px){.identity{flex-direction:column}.leaders{grid-template-columns:1fr}.profile{padding:22px 0}}
@media(max-width:1100px){.player-intelligence-grid,.team-rank-groups,.team-innings{grid-template-columns:1fr}.team-season-strip,.team-metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.player-log-filters{grid-template-columns:1fr 1fr}.filter-scope{grid-column:1/-1}.player-average-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.team-season-strip,.team-metric-grid{grid-template-columns:1fr 1fr}.log-toolbar,.schedule-toolbar{align-items:flex-start;flex-direction:column}.team-rank-grid article{grid-template-columns:minmax(130px,1fr) 70px}.team-rank-grid article>i{display:none}.player-log-filters{grid-template-columns:1fr}.filter-scope{grid-column:auto}.player-average-grid{grid-template-columns:1fr 1fr}.all-average-head{align-items:flex-start;flex-direction:column}}
</style>
