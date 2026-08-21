<script setup>
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../services/api'
import MetricCard from '../components/ui/MetricCard.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import TrendChart from '../components/charts/TrendChart.vue'
import AnalyticsChart from '../components/charts/AnalyticsChart.vue'
import MetricComparison from '../components/charts/MetricComparison.vue'
import ProbabilityRing from '../components/charts/ProbabilityRing.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import PlayerHeadshot from '../components/player/PlayerHeadshot.vue'
import MatchupPersonnel from '../components/game/MatchupPersonnel.vue'
import ContextBack from '../components/navigation/ContextBack.vue'
import AnimatedNumber from '../components/ui/AnimatedNumber.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import LoadError from '../components/ui/LoadError.vue'
import { createSharedPoller } from '../services/polling'
import SavePredictionButton from '../features/auth/components/SavePredictionButton.vue'

const route = useRoute()
const fromBuilder = computed(() => route.query.from === 'builder')
const game = ref()
const loaded = ref(false)
const refreshing = ref(false)
const error = ref('')
const now = ref(Date.now())
const isFinal = computed(() => /final|completed|game over/i.test(game.value?.status || ''))
const actualSide = computed(() => Number(game.value?.home?.score) === Number(game.value?.away?.score) ? null : Number(game.value?.home?.score) > Number(game.value?.away?.score) ? 'home' : 'away')
const actualWinner = computed(() => actualSide.value ? game.value?.[actualSide.value] : null)
const projectedTeam = computed(() => game.value?.projection?.projected_side === 'home' ? game.value?.home : game.value?.away)
const pickCorrect = computed(() => Boolean(actualSide.value && game.value?.projection?.projected_side === actualSide.value))
const savableProjection = computed(() => ({
  sport: 'baseball',
  league: 'MLB',
  eventId: String(game.value?.id || route.params.id),
  predictionType: 'moneyline',
  selection: projectedTeam.value?.name || '',
  probability: selectedProbability.value,
  modelName: game.value?.projection?.model?.name || 'NINTH moneyline',
  modelVersion: String(game.value?.projection?.model?.version || game.value?.projection?.model?.holdout_season || 'production'),
  generatedAt: game.value?.contextUpdatedAt || new Date().toISOString(),
  inputSnapshot: { completeness: game.value?.projection?.input_completeness, projectedSide: projectedSide.value },
  output: { awayWinProbability: game.value?.projection?.away_win_probability, homeWinProbability: game.value?.projection?.home_win_probability },
  metadata: { matchup: `${game.value?.away?.name} at ${game.value?.home?.name}`, source: 'matchup' },
}))
let poller
let clockTimer
let pendingReload = false
const uiPollSeconds = computed(() => game.value?.statusCode === 'Live' ? 10 : 300)
const refreshLabel = computed(() => game.value?.partial ? 'Official matchup loaded · model inputs are next' : game.value?.projectionRefreshSeconds ? `Model reassesses every ${game.value.projectionRefreshSeconds}s · screen syncs every ${uiPollSeconds.value}s` : 'Final data locked')
const statusLabel = status => status === 'confirmed' ? 'CONFIRMED' : status === 'predicted' ? 'PREDICTED' : 'PENDING'
const projectionTime = computed(() => game.value?.contextUpdatedAt ? Date.parse(game.value.contextUpdatedAt) : null)
const projectionAge = computed(() => projectionTime.value ? Math.max(0, Math.floor((now.value - projectionTime.value) / 1000)) : null)
const projectionExact = computed(() => projectionTime.value ? new Date(projectionTime.value).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'}) : 'Awaiting projection')
const projectionCadence = computed(() => game.value?.projectionRefreshSeconds ? `AUTO ${game.value.projectionRefreshSeconds}s` : 'LOCKED')
const projectionRelative = computed(() => {
  if (refreshing.value) return 'UPDATING'
  if (!game.value?.projectionRefreshSeconds && projectionTime.value) return 'FINAL SNAPSHOT'
  const seconds = projectionAge.value
  if (seconds === null) return 'PENDING'
  if (seconds < 5) return 'JUST NOW'
  if (seconds < 60) return `${seconds}s AGO`
  const minutes = Math.floor(seconds / 60)
  return minutes < 60 ? `${minutes}m AGO` : `${Math.floor(minutes / 60)}h AGO`
})
const projectionFreshness = computed(() => {
  if (refreshing.value) return 'syncing'
  if (!game.value?.projectionRefreshSeconds && projectionTime.value) return 'locked'
  if (projectionAge.value === null) return 'stale'
  const expected = game.value?.projectionRefreshSeconds || 60
  return projectionAge.value <= expected + 5 ? 'fresh' : projectionAge.value <= expected * 2 ? 'aging' : 'stale'
})
const projectedSide = computed(() => game.value?.projection?.projected_side || 'home')
const selectedProbability = computed(() => Number(game.value?.projection?.[`${projectedSide.value}_win_probability`] || 0))
const displayedProbabilities = computed(() => {
  const away = Math.round(Math.max(0, Math.min(1, Number(game.value?.projection?.away_win_probability || 0))) * 1000) / 10
  return { away, home: Number((100 - away).toFixed(1)) }
})
const totals = computed(() => game.value?.totalsProjection)
const totalSelectionAvailable = computed(() => Boolean(
  totals.value?.recommended_side
  && totals.value?.recommended_line !== null
  && totals.value?.recommended_line !== undefined
  && (isFinal.value || totals.value?.selection_available !== false),
))
const totalsBaselineBrier = computed(() => Number(totals.value?.model?.unseen_baseline?.mean_brier || totals.value?.model?.incumbent_unseen_brier || 0))
const totalsBrierSkill = computed(() => totalsBaselineBrier.value ? (totalsBaselineBrier.value - Number(totals.value?.model?.unseen_2025_2026?.mean_brier || 0)) / totalsBaselineBrier.value : 0)
const totalsMarketTime = computed(() => totals.value?.line_market?.observed_at ? new Date(totals.value.line_market.observed_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}) : 'not currently listed')
const finalTotalRuns = computed(() => Number(game.value?.home?.score || 0) + Number(game.value?.away?.score || 0))
const totalPickCorrect = computed(() => totals.value?.available && isFinal.value && totalSelectionAvailable.value ? (totals.value.recommended_side === 'over' ? finalTotalRuns.value > totals.value.recommended_line : finalTotalRuns.value < totals.value.recommended_line) : null)
const totalPct = value => `${(Number(value || 0) * 100).toFixed(1)}%`
const totalImpact = reason => `${(Math.abs(Number(reason.impact || 0)) * 100).toFixed(1)} points`
const supportingReasons = computed(() => (game.value?.projection?.reasons || []).filter(reason => reason.direction === projectedSide.value))
const opposingReasons = computed(() => (game.value?.projection?.reasons || []).filter(reason => reason.direction !== projectedSide.value))
const decisiveFactor = computed(() => supportingReasons.value[0] || null)
const primaryRisk = computed(() => opposingReasons.value[0] || null)
const starterByTeam = computed(() => new Map((game.value?.starterProfiles || []).map(row => [row.team, row])))
const starters = computed(() => ({ away: starterByTeam.value.get(game.value?.away?.name) || game.value?.starterProfiles?.[0], home: starterByTeam.value.get(game.value?.home?.name) || game.value?.starterProfiles?.[1] }))
const relativePair = (left, right, lower = false) => {
  const a = Number(left), b = Number(right)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return [0, 0]
  if (lower) { const floor = Math.min(a || 999, b || 999); return [a ? floor / a * 100 : 0, b ? floor / b * 100 : 0] }
  const ceiling = Math.max(Math.abs(a), Math.abs(b), 1)
  return [Math.max(0, a / ceiling * 100), Math.max(0, b / ceiling * 100)]
}
const comparisonRow = (label, left, right, digits = 2, lower = false) => { const [leftScore, rightScore] = relativePair(left, right, lower); return { label, left: leftScore, right: rightScore, leftDisplay: metric(left, digits), rightDisplay: metric(right, digits) } }
const starterComparison = computed(() => {
  const away = starters.value.away || {}, home = starters.value.home || {}
  return [comparisonRow('ERA', away.era, home.era, 2, true), comparisonRow('WHIP', away.whip, home.whip, 2, true), comparisonRow('Strikeouts', away.strikeouts, home.strikeouts, 0), comparisonRow('K / BB', Number(away.strikeouts) / Math.max(1, Number(away.walks)), Number(home.strikeouts) / Math.max(1, Number(home.walks)), 2)]
})
const offenseComparison = computed(() => {
  const byTeam = new Map((game.value?.comparison || []).map(row => [row.team, row.values || []])), away = byTeam.get(game.value?.away?.abbr) || [], home = byTeam.get(game.value?.home?.abbr) || []
  return [comparisonRow('AVG', away[0], home[0], 3), comparisonRow('OBP', away[1], home[1], 3), comparisonRow('SLG', away[2], home[2], 3), comparisonRow('OPS', away[3], home[3], 3), comparisonRow('Staff ERA', away[7], home[7], 2, true)]
})
const bullpenComparison = computed(() => {
  const away = game.value?.pitchingMatchup?.away || {}, home = game.value?.pitchingMatchup?.home || {}, awayWork = game.value?.modelContext?.away?.bullpen_recent_pitches, homeWork = game.value?.modelContext?.home?.bullpen_recent_pitches
  return [comparisonRow('Bullpen ERA', away.bullpen_era, home.bullpen_era, 2, true), comparisonRow('Runs / game', away.bullpen_runs_per_game, home.bullpen_runs_per_game, 2, true), comparisonRow('3-day pitches', awayWork, homeWork, 0, true)]
})
const formChart = computed(() => {
  const away = [...(game.value?.recentForm?.away || [])].reverse(), home = [...(game.value?.recentForm?.home || [])].reverse(), length = Math.max(away.length, home.length)
  return { labels: Array.from({ length }, (_, index) => `G${index + 1}`), series: [{ label: `${game.value?.away?.abbr} runs`, values: away.map(row => Number(row.team_score)) }, { label: `${game.value?.home?.abbr} runs`, values: home.map(row => Number(row.team_score)) }] }
})
const leagueContext = computed(() => game.value?.leagueContext || null)
const leagueTeam = side => leagueContext.value?.teams?.[side] || {}
const rankingGroups = ['OFFENSE', 'RUN PREVENTION']
const rankingsFor = (side, group) => (leagueTeam(side).rankings || []).filter(row => row.group === group)
const rankTone = row => row.rank <= 5 ? 'elite' : row.rank >= Math.max(26, row.teams - 4) ? 'concern' : 'middle'
const rankBand = row => row.rank <= 5 ? 'MLB ELITE' : row.rank <= 10 ? 'TOP THIRD' : row.rank >= Math.max(26, row.teams - 4) ? 'BOTTOM FIVE' : row.rank >= Math.ceil(row.teams * 2 / 3) ? 'BOTTOM THIRD' : 'LEAGUE MIDDLE'
const rankingInsight = side => {
  const rows = [...(leagueTeam(side).rankings || [])]
  if (!rows.length) return 'League rank context is unavailable.'
  const best = [...rows].sort((a, b) => a.rank - b.rank)[0]
  const concern = [...rows].sort((a, b) => b.rank - a.rank)[0]
  return `Best position: #${best.rank} ${best.label}. Clearest pressure point: #${concern.rank} ${concern.label}.`
}
const inningDistribution = side => leagueTeam(side).inning_distribution || {}
const inningLabels = computed(() => inningDistribution('away').labels || inningDistribution('home').labels || [])
const inningScoredSeries = computed(() => [
  { label: `${game.value?.away?.abbr} scored`, values: inningDistribution('away').scored_per_game || [], color: '#809fff' },
  { label: `${game.value?.home?.abbr} scored`, values: inningDistribution('home').scored_per_game || [], color: '#d6ff61' },
])
const inningAllowedSeries = computed(() => [
  { label: `${game.value?.away?.abbr} allowed`, values: inningDistribution('away').allowed_per_game || [], color: '#809fff' },
  { label: `${game.value?.home?.abbr} allowed`, values: inningDistribution('home').allowed_per_game || [], color: '#d6ff61' },
])
const phaseRows = side => (inningDistribution(side).phases || []).filter(row => row.label !== 'EXTRAS')
const leagueThrough = computed(() => leagueContext.value?.through ? new Date(`${leagueContext.value.through}T00:00:00`).toLocaleDateString([], { month:'short', day:'numeric', year:'numeric' }) : 'the latest completed games')
const reasoningSummary = computed(() => {
  if (!game.value?.projection?.available || !projectedTeam.value) return ''
  const lead = isFinal.value ? 'The archived pregame model selected' : 'The current model selects'
  const support = supportingReasons.value.map(reason => reason.label).join(', ')
  const resistance = opposingReasons.value.map(reason => reason.label).join(', ')
  return `${lead} ${projectedTeam.value.name} at ${(selectedProbability.value * 100).toFixed(1)}%. ${support ? `Its strongest supporting signals are ${support}.` : ''}${resistance ? ` The main counterweights are ${resistance}.` : ''}`
})
const missingInputs = computed(() => {
  const context = game.value?.modelContext
  if (!context) return ['Official matchup context is still loading']
  const missing = []
  for (const side of ['away', 'home']) {
    const team = game.value?.[side]?.abbr || side
    if (context[side]?.starter_status !== 'confirmed') missing.push(`${team} starter not confirmed`)
    if (!context[side]?.lineup_confirmed) missing.push(`${team} lineup not confirmed`)
    if (context[side]?.bullpen_status !== 'confirmed') missing.push(`${team} bullpen not confirmed`)
  }
  if (context.weather?.available === false || context.weather?.temperature == null) missing.push('Game-time weather unavailable')
  return missing
})
const reasonTeam = reason => game.value?.[reason.direction]
const reasonRole = reason => reason.direction === projectedSide.value ? 'SUPPORTS THE PICK' : 'PUSHES TOWARD THE OPPONENT'
const reasonImpact = reason => `${(Math.abs(Number(reason.impact || 0)) * 100).toFixed(1)} percentage points`
const metric = (value, digits = 0) => value === null || value === undefined || value === '' ? '—' : Number(value).toFixed(digits)
const shortStartDate = value => value ? new Date(`${value}T00:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '—'
const startOpponent = start => `${start?.venue === 'home' ? 'vs' : '@'} ${start?.opponent || 'Unknown'}`
const recentStartAverages = starts => {
  const rows = starts || []
  if (!rows.length) return null
  const average = key => (rows.reduce((sum, row) => sum + Number(row?.[key] || 0), 0) / rows.length).toFixed(1)
  const innings = rows.reduce((sum, row) => {
    const [whole = '0', fraction = '0'] = String(row?.innings || '0').split('.')
    return sum + Number(whole || 0) * 3 + Math.min(2, Number(fraction?.[0] || 0))
  }, 0) / rows.length / 3
  return {
    innings: innings.toFixed(1), hits: average('hits'), runs: average('runs'),
    earned_runs: average('earned_runs'), walks: average('walks'),
    strikeouts: average('strikeouts'), home_runs: average('home_runs'),
    pitches: average('pitches'),
  }
}
const load = async () => {
  if (refreshing.value) { pendingReload = true; return }
  const requestedId = String(route.params.id)
  const started = Date.now()
  refreshing.value = true
  error.value = ''
  try {
    if (!game.value || String(game.value.id) !== String(route.params.id)) {
      loaded.value = false
      const summary = await api.gameSummary(requestedId)
      if (String(route.params.id) !== requestedId) { pendingReload = true; return }
      game.value = summary
    }
    const detail = await api.game(requestedId)
    if (String(route.params.id) !== requestedId) { pendingReload = true; return }
    game.value = detail
    loaded.value = true
  } catch (caught) {
    error.value = caught?.message || 'The matchup could not be loaded.'
  } finally {
    const remaining = 280 - (Date.now() - started)
    if (remaining > 0 && game.value) await new Promise(resolve => window.setTimeout(resolve, remaining))
    refreshing.value = false
    if (pendingReload) { pendingReload = false; queueMicrotask(load) }
  }
}
const syncWhenActive = () => { if (document.visibilityState === 'visible') poller?.trigger() }
onMounted(()=>{poller=createSharedPoller({key:()=>`matchup:${route.params.id}`,task:load,interval:()=>isFinal.value?0:uiPollSeconds.value*1000});poller.start();clockTimer=window.setInterval(()=>{now.value=Date.now()},1000);window.addEventListener('focus',syncWhenActive);window.addEventListener('online',syncWhenActive)})
onBeforeUnmount(() => { poller?.stop(); window.clearInterval(clockTimer);window.removeEventListener('focus',syncWhenActive);window.removeEventListener('online',syncWhenActive) })
watch(() => route.params.id, () => poller?.trigger())
</script>

<template>
  <div class="game-page">
  <div class="return-builder"><ContextBack fallback="/schedule"/><span v-if="fromBuilder">Your draft selections and builder settings are saved.</span></div>
  <div v-if="game" class="view">
    <section class="match panel">
      <div class="matchup-team away"><TeamLogo :team="game.away" :size="76"/><div><span class="eyebrow">AWAY · {{ game.away.record || 'MLB' }}</span><h2><RouterLink :to="`/teams/${game.away.id}`">{{ game.away.name }}</RouterLink></h2></div></div>
      <div class="match-meta"><span class="eyebrow">{{ game.status }} · {{ game.time }}</span><strong>VS</strong><p>{{ game.stadium }} · {{ game.weather }}</p></div>
      <div class="matchup-team home"><div><span class="eyebrow">HOME · {{ game.home.record || 'MLB' }}</span><h2><RouterLink :to="`/teams/${game.home.id}`">{{ game.home.name }}</RouterLink></h2></div><TeamLogo :team="game.home" :size="76"/></div>
      <div class="prob"><small>{{ isFinal ? 'FINAL MODEL REVIEW' : 'PROJECTION MONITOR' }}</small><strong class="mono">{{ refreshing ? 'SYNCING' : isFinal ? 'RESULT LOCKED' : 'LIVE INPUTS' }}</strong><p>{{ refreshLabel }}<template v-if="game.contextUpdatedAt"> · checked {{ new Date(game.contextUpdatedAt).toLocaleTimeString([], {hour:'numeric',minute:'2-digit',second:'2-digit'}) }}</template></p></div>
    </section>
    <section v-if="game.projection?.available" class="opening-verdict panel">
      <div class="verdict-pick"><span class="eyebrow">MODEL VERDICT</span><h2>{{ projectedTeam?.name }}</h2><p>Favored by <b>{{ ((selectedProbability-.5)*100).toFixed(1) }} probability points</b> over a neutral matchup.</p><ProbabilityRing :value="selectedProbability" :label="`${projectedTeam?.abbr} win`" :detail="`${game.projection.confidence_label} confidence · ${Math.round(game.projection.input_completeness*100)}% inputs`" :size="178"/><SavePredictionButton :prediction="savableProjection"/></div>
      <div class="verdict-score"><span class="eyebrow">EXPECTED GAME SHAPE</span><strong>{{ totals?.expected_total_runs ? `${totals.expected_total_runs.toFixed(1)} runs` : 'Total pending' }}</strong><p>{{ totals?.prediction_interval_80 ? `80% interval ${totals.prediction_interval_80[0]}–${totals.prediction_interval_80[1]}` : 'The exact score distribution is still loading.' }}</p><div><template v-for="side in ['away','home']" :key="side"><RouterLink v-if="starters[side]?.id" :to="`/players/${starters[side].id}`"><PlayerHeadshot :player="starters[side]" :size="48"/><span><small>{{game[side].abbr}} STARTER</small><b>{{starters[side].name}}</b><em>{{starters[side].era??'—'}} ERA · {{starters[side].whip??'—'}} WHIP</em></span></RouterLink></template></div></div>
      <div class="verdict-signals"><article><span>DECISIVE FACTOR</span><b>{{decisiveFactor?.label||'No single dominant signal'}}</b><p v-if="decisiveFactor">Moves the forecast {{reasonImpact(decisiveFactor)}} toward {{reasonTeam(decisiveFactor)?.name}}.</p></article><article class="risk"><span>PRIMARY RISK</span><b>{{primaryRisk?.label||missingInputs[0]||'No tracked counter-signal'}}</b><p v-if="primaryRisk">Currently pushes {{reasonImpact(primaryRisk)}} toward {{reasonTeam(primaryRisk)?.name}}.</p><p v-else>{{missingInputs.length?`${missingInputs.length} live inputs remain unresolved.`:'All tracked inputs are confirmed.'}}</p></article></div>
    </section>
    <LoadError v-if="error && !loaded" :message="error" @retry="load"/>
    <div v-else-if="!loaded" class="panel load detail-load"><span class="load-pulse"></span><div><b>Matchup ready</b><small>Loading model projection, confirmed inputs and official player statistics…</small></div></div>
    <template v-else>
    <div v-if="game.contextUpdatedAt" class="projection-stamp panel" :class="projectionFreshness"><i></i><span><small>LAST PROJECTION · {{ projectionCadence }}</small><b class="mono">{{ projectionExact }}</b></span><em>{{ projectionRelative }}</em></div>
    <nav class="matchup-index" aria-label="Matchup analysis sections"><span>JUMP TO</span><a href="#league-context">MLB RANKS</a><a href="#starter-edge">STARTERS</a><a href="#moneyline-evidence">MONEYLINE</a><a href="#totals-evidence">TOTALS</a><a href="#offense-evidence">OFFENSE</a><a href="#pitching-evidence">RUN PREVENTION</a></nav>
    <div class="grid-auto"><MetricCard v-for="metric in game.metrics" :key="metric.label" v-bind="metric" /></div>
    <SectionCard id="league-context" title="MLB rank and inning pressure" :subtitle="`Point-in-time season context through ${leagueThrough} · league ranks compare all ${leagueContext?.team_count || 30} clubs`">
      <div v-if="leagueContext?.available" class="league-intelligence">
        <div class="rank-board">
          <article v-for="side in ['away','home']" :key="side" class="rank-team" :class="side">
            <header><TeamLogo :team="game[side]" :size="44"/><div><small>{{ side.toUpperCase() }} · {{ game[side].abbr }}</small><h3>{{ game[side].name }}</h3></div><span>{{ inningDistribution(side).sample_games || 0 }} GAMES</span></header>
            <p>{{ rankingInsight(side) }}</p>
            <section v-for="group in rankingGroups" :key="group">
              <div class="rank-group-title"><b>{{ group }}</b><small>RANK / {{ leagueContext.team_count }}</small></div>
              <div v-for="row in rankingsFor(side, group)" :key="row.key" class="rank-row" :class="rankTone(row)">
                <span><b>{{ row.label }}</b><small>{{ row.display }} · {{ row.higher_is_better ? 'higher' : 'lower' }} is stronger</small></span>
                <i><em :style="{width:`${Math.max(4,row.percentile)}%`}"></em></i>
                <strong class="mono">#{{ row.rank }}<small>{{ rankBand(row) }}</small></strong>
              </div>
            </section>
          </article>
        </div>
        <div class="inning-intro"><div><span class="eyebrow">SCORING TIMING</span><h3>Where each team creates—and concedes—runs</h3></div><p>Each bar is that inning's average contribution per completed team game. The 10+ bucket combines all extra innings, so the full series adds back to season runs per game.</p></div>
        <div class="inning-chart-grid">
          <article><header><div><small>OFFENSIVE DISTRIBUTION</small><b>Runs scored by inning</b></div><span>RUNS / TEAM GAME</span></header><AnalyticsChart type="bar" :labels="inningLabels" :series="inningScoredSeries" :height="300" unit="runs / game" begin-at-zero/></article>
          <article><header><div><small>RUN-PREVENTION DISTRIBUTION</small><b>Runs allowed by inning</b></div><span>RUNS / TEAM GAME</span></header><AnalyticsChart type="bar" :labels="inningLabels" :series="inningAllowedSeries" :height="300" unit="runs / game" begin-at-zero/></article>
        </div>
        <div class="phase-board">
          <article v-for="side in ['away','home']" :key="side" :class="side">
            <header><TeamLogo :team="game[side]" :size="34"/><div><small>{{ game[side].abbr }} GAME PHASES</small><b>{{ inningDistribution(side).runs_scored_per_game }} scored · {{ inningDistribution(side).runs_allowed_per_game }} allowed</b></div></header>
            <div><span v-for="phase in phaseRows(side)" :key="phase.label"><small>{{ phase.label }} · INN {{ phase.innings }}</small><b class="mono">{{ phase.scored_per_game }} FOR / {{ phase.allowed_per_game }} AGAINST</b><em>{{ phase.scored_share }}% of offense · {{ phase.allowed_share }}% of runs allowed</em></span></div>
            <footer><span>Scores in 1st <b>{{ inningDistribution(side).scoring_game_rate?.[0] ?? '—' }}%</b></span><span>Allows in 1st <b>{{ inningDistribution(side).allowing_game_rate?.[0] ?? '—' }}%</b></span></footer>
          </article>
        </div>
        <p class="league-source">Source · {{ leagueContext.source }}. Rankings and inning distributions stop before this matchup; they are descriptive context, not a guarantee of today's game script.</p>
      </div>
      <p v-else class="unavailable">{{ leagueContext?.message || 'League rankings and inning distributions are still loading.' }}</p>
    </SectionCard>
    <SectionCard id="starter-edge" title="Starting pitcher advantage" subtitle="Relative matchup comparison · lower ERA and WHIP are treated as stronger run prevention">
      <div class="pitcher-visual"><MetricComparison :rows="starterComparison" :left-label="game.away.abbr" :right-label="game.home.abbr"/><div class="pitcher-identities"><template v-for="side in ['away','home']" :key="side"><RouterLink v-if="starters[side]?.id" :to="`/players/${starters[side].id}`"><PlayerHeadshot :player="starters[side]" :size="76"/><span><small>{{side.toUpperCase()}} STARTER</small><b>{{starters[side].name}}</b><em>OPEN PLAYER PROFILE</em></span></RouterLink></template></div></div>
    </SectionCard>
    <SectionCard id="moneyline-evidence" :title="isFinal ? 'Final model review' : 'Market-free moneyline projection'" :subtitle="isFinal ? 'Original forecast compared with the official final result' : 'Calibrated from baseball data only · no odds or sportsbook inputs'">
      <div v-if="game.projection?.available" class="projection">
        <div v-if="isFinal" class="final-review"><div><small>OFFICIAL FINAL</small><strong class="mono">{{ game.away.abbr }} {{ game.away.score }}–{{ game.home.score }} {{ game.home.abbr }}</strong><span>{{ actualWinner ? `${actualWinner.name} won` : 'Game finished tied' }}</span></div><div><small>MODEL OUTCOME</small><b :class="pickCorrect ? 'correct' : 'missed'">{{ actualSide ? (pickCorrect ? 'PICK CORRECT' : 'PICK MISSED') : 'NO DECISION' }}</b><span>Original pick · {{ projectedTeam?.name }}</span></div></div>
        <div class="probability-row"><div><TeamLogo :team="game.away" :size="48"/><span><small>{{ game.away.abbr }} {{ isFinal ? 'FORECAST' : 'WIN' }}</small><strong class="mono"><AnimatedNumber :value="displayedProbabilities.away" :decimals="1" suffix="%"/></strong></span></div><div class="model-pick"><small>{{ isFinal ? 'ORIGINAL MODEL PICK' : 'PROJECTED SIDE' }}</small><b>{{ projectedTeam?.name }}</b><span>{{ isFinal ? 'Archived forecast · not a postgame chance' : 'Decision support · not a guarantee' }}</span></div><div class="home-prob"><span><small>{{ game.home.abbr }} {{ isFinal ? 'FORECAST' : 'WIN' }}</small><strong class="mono"><AnimatedNumber :value="displayedProbabilities.home" :decimals="1" suffix="%"/></strong></span><TeamLogo :team="game.home" :size="48"/></div></div>
        <div class="probability-bar"><i :style="{width:`${game.projection.away_win_probability*100}%`}"></i><i :style="{width:`${game.projection.home_win_probability*100}%`}"></i></div>
        <div class="confidence-summary"><div><small>MODEL CONFIDENCE</small><strong class="mono">{{ game.projection.confidence_score }}/100 <em :class="game.projection.confidence_label.toLowerCase()">{{ game.projection.confidence_label }}</em></strong><p>{{ game.projection.confidence_explanation }}</p></div><div v-if="game.projection.historical_tier"><small>SIMILAR WALK-FORWARD PICKS</small><strong class="mono">{{ Math.round(game.projection.historical_tier.accuracy*100) }}% accurate</strong><p>{{ game.projection.historical_tier.games.toLocaleString() }} games · {{ Math.round(game.projection.historical_tier.coverage*100) }}% of evaluated matchups</p></div><div><small>LIVE INPUT COVERAGE</small><strong class="mono">{{ Math.round(game.projection.input_completeness*100) }}%</strong><p>Starter, lineup, bullpen and weather availability</p></div></div>
        <details class="deep-evidence" :open="!isFinal"><summary><span><b>DEEP MODEL EVIDENCE</b><small>Drivers, input coverage, unresolved context and audit metrics</small></span><em>{{isFinal?'EXPAND ARCHIVE':'LIVE DETAIL'}}</em></summary>
        <section class="projection-reasoning">
          <header><div><span class="eyebrow">WHY THIS PROJECTION</span><h3>{{ isFinal ? 'Why the model made this pick' : `Why ${projectedTeam?.name} is favored` }}</h3></div><span class="reasoning-live" :class="projectionFreshness"><i></i>{{ refreshing ? 'SYNCING INPUTS' : `AUTO-SYNC · ${uiPollSeconds}s` }}</span></header>
          <p class="reasoning-summary">{{ reasoningSummary }}</p>
          <div v-if="game.projection.reasons?.length" class="reason-grid">
            <article v-for="reason in game.projection.reasons" :key="reason.feature" :class="[reason.direction,{counter:reason.direction!==projectedSide}]">
              <span :class="reason.direction" :aria-label="`${reason.direction} team ${reasonTeam(reason)?.abbr}`">{{ reasonTeam(reason)?.abbr }}</span>
              <div><small>{{ reasonRole(reason) }}</small><b>{{ reason.label }}</b><p>Compared with a neutral value, this signal moves the forecast about <strong>{{ reasonImpact(reason) }}</strong> toward {{ reasonTeam(reason)?.name }}.</p></div>
            </article>
          </div>
          <div class="reasoning-status"><div><small>CURRENTLY INCLUDED</small><b>{{ Math.round(game.projection.input_completeness*100) }}% official input coverage</b><span>The model automatically reassesses when official starters, lineups, bullpen status, weather or game state changes.</span></div><div><small>STILL UNRESOLVED</small><template v-if="missingInputs.length"><span v-for="item in missingInputs" :key="item">{{ item }}</span></template><b v-else>All tracked matchup inputs are confirmed</b></div></div>
          <aside>These are counterfactual model effects, not claims of cause. Signals interact inside a nonlinear model, so their individual percentage-point effects will not add exactly to the displayed win probability.</aside>
        </section>
        <div v-if="game.projection.circumstance_alerts?.length" class="context-alerts"><article v-for="alert in game.projection.circumstance_alerts" :key="alert.type+alert.message" :class="alert.level"><b>{{ alert.type.replaceAll('_',' ') }}</b><span>{{ alert.message }}</span></article></div>
        <div v-if="game.modelContext" class="context-grid">
          <article v-for="side in ['away','home']" :key="side"><small>{{ game[side].abbr }} INPUTS</small><b>{{ game.modelContext[side]?.starter_name || 'Starter pending' }}</b><span class="input-state" :class="game.modelContext[side]?.starter_status">{{ statusLabel(game.modelContext[side]?.starter_status) }} STARTER</span><span>ERA {{ metric(game.modelContext[side]?.starter_era, 2) }} · WHIP {{ metric(game.modelContext[side]?.starter_whip, 2) }}</span><span>{{ game.modelContext[side]?.lineup_confirmed ? 'Confirmed lineup' : 'Projected lineup' }} · OPS {{ metric(game.modelContext[side]?.lineup_ops, 3) }}</span><span class="input-state" :class="game.modelContext[side]?.bullpen_status">{{ statusLabel(game.modelContext[side]?.bullpen_status) }} BULLPEN</span><span>{{ metric(game.modelContext[side]?.bullpen_recent_pitches) }} pitches used / previous 3 days</span></article>
          <article><small>WEATHER INPUT</small><b>{{ game.modelContext.weather?.condition || 'Conditions pending' }}</b><span>{{ metric(game.modelContext.weather?.temperature) }}°F · {{ metric(game.modelContext.weather?.wind_speed) }} mph wind</span><span>{{ game.modelContext.weather?.source || 'Source pending' }}</span></article>
        </div>
        <footer class="model-audit"><span>{{ game.projection.model.holdout_season }} HOLDOUT ACCURACY <b class="mono">{{ (game.projection.model.accuracy*100).toFixed(1) }}%</b></span><span>WALK-FORWARD ACCURACY <b class="mono">{{ (game.projection.model.walk_forward.accuracy*100).toFixed(1) }}%</b></span><span>BRIER SCORE <b class="mono">{{ game.projection.model.brier_score }}</b></span><span>TRAINING GAMES <b class="mono">{{ game.projection.model.deployment_training_games.toLocaleString() }}</b></span></footer>
        </details>
      </div>
      <p v-else class="unavailable">{{ game.projection?.message || 'The local projection is unavailable.' }}</p>
    </SectionCard>
    <SectionCard id="totals-evidence" title="Market-free total runs projection" subtitle="The model scores currently displayed full-game lines · prices are excluded">
      <div v-if="totals?.available" class="totals-projection">
        <div v-if="!isFinal" class="totals-market-status" :class="{ unavailable: !totalSelectionAvailable }">
          <span><small>CURRENT FULL-GAME OFFER</small><b>{{ totalSelectionAvailable ? `${totals.line_market.lines.length} LISTED TOTALS` : 'NO LISTING FOUND' }}</b></span>
          <p v-if="totalSelectionAvailable">{{ totals.line_market.lines.join(' · ') }} <em>Captured {{ totalsMarketTime }} · thresholds only, no prices</em></p>
          <p v-else>MelBet generally lists only games inside the next 24 hours. The run forecast remains visible, but NINTH will not recommend a total until a current line is matched.</p>
        </div>
        <div class="totals-call">
          <span><small>PROJECTED GAME TOTAL</small><strong class="mono"><AnimatedNumber :value="totals.expected_total_runs" :decimals="1"/> RUNS</strong><em>80% interval {{ totals.prediction_interval_80[0] }}–{{ totals.prediction_interval_80[1] }}</em></span>
          <div><small>{{isFinal?'ARCHIVED TOTALS PICK':totalSelectionAvailable?'BEST CURRENTLY LISTED LINE':'AWAITING LISTED LINE'}}</small><strong>{{ totalSelectionAvailable ? `${totals.recommended_side.toUpperCase()} ${totals.recommended_line}` : 'MODEL ONLY' }}</strong><em v-if="isFinal">Final total {{finalTotalRuns}} · {{totalPickCorrect?'PICK CORRECT':'PICK MISSED'}}</em><em v-else-if="totalSelectionAvailable">{{ totalPct(totals.recommended_probability) }} {{totals.projection_phase==='live'?'live conditional':'calibrated'}} probability · {{ totals.confidence_label }} confidence</em><em v-else>No selectable totals recommendation is issued without a current listing.</em></div>
          <span><small>OFFICIAL INPUT COVERAGE</small><strong class="mono">{{ Math.round(totals.input_completeness*100) }}%</strong><em>{{ totals.confidence_explanation }}</em></span>
        </div>
        <div v-if="totalSelectionAvailable" class="total-thresholds">
          <article v-for="row in totals.thresholds" :key="row.line" :class="{recommended:row.line===totals.recommended_line}"><small>TOTAL {{ row.line }}</small><div><span>OVER <b class="mono">{{ totalPct(row.over_probability) }}</b></span><span>UNDER <b class="mono">{{ totalPct(row.under_probability) }}</b></span><span v-if="row.push_probability">PUSH <b class="mono">{{ totalPct(row.push_probability) }}</b></span></div></article>
        </div>
        <section class="total-reasons"><header><span class="eyebrow">WHY THIS TOTAL</span><p>NINTH selects the strongest calibrated side only among the full-game totals currently displayed for this exact matchup. Prices never enter the model or ranking.</p></header><div><article v-for="reason in totals.reasons" :key="reason.feature"><span :class="reason.direction">{{ reason.direction.toUpperCase() }}</span><b>{{ reason.label }}</b><small>{{ totalImpact(reason) }} toward {{ reason.direction }}</small></article></div></section>
        <footer class="model-audit"><span>UNSEEN 2025–26 BRIER <b class="mono">{{ totals.model.unseen_2025_2026.mean_brier.toFixed(5) }}</b></span><span>PRIOR MODEL BRIER <b class="mono">{{ totalsBaselineBrier.toFixed(5) }}</b></span><span>BRIER IMPROVEMENT <b class="mono">{{ (totalsBrierSkill*100).toFixed(2) }}%</b></span><span>TRAINING GAMES <b class="mono">{{ totals.model.training_games.toLocaleString() }}</b></span></footer>
      </div>
      <p v-else class="unavailable">{{ totals?.message || 'The totals projection is unavailable.' }}</p>
    </SectionCard>
    <SectionCard id="offense-evidence" title="Offensive matchup" subtitle="Season production and the latest five-game scoring path">
      <div class="offense-visual"><MetricComparison :rows="offenseComparison" :left-label="game.away.abbr" :right-label="game.home.abbr"/><div><header><span class="eyebrow">RECENT RUN PRODUCTION</span><b>Which offense is arriving in better form?</b></header><AnalyticsChart :labels="formChart.labels" :series="formChart.series" :height="285" begin-at-zero/><p>Runs shown are official results from each team's latest captured games. The trend is descriptive, not a standalone forecast.</p></div></div>
    </SectionCard>
    <SectionCard title="Last 5 games" subtitle="Most recent completed games from the official MLB schedule">
      <div class="form-grid">
        <article v-for="side in ['away','home']" :key="side" class="form-team">
          <header><TeamLogo :team="game[side]" :size="38"/><div><strong>{{ game[side].name }}</strong><small>{{ side.toUpperCase() }} TEAM</small></div><span class="form-record mono">{{ game.recentForm?.[side]?.filter(item=>item.result==='W').length || 0 }}–{{ game.recentForm?.[side]?.filter(item=>item.result==='L').length || 0 }}</span></header>
          <RouterLink v-for="result in game.recentForm?.[side]" :key="result.game_id" :to="`/games/${result.game_id}`" class="form-row"><i :class="result.result==='W'?'win':'loss'">{{ result.result }}</i><span><b>{{ result.location }} {{ result.opponent }}</b><small>{{ result.date }}</small></span><strong class="mono">{{ result.team_score }}–{{ result.opponent_score }}</strong></RouterLink>
          <p v-if="!game.recentForm?.[side]?.length" class="unavailable">No completed games were returned for this team.</p>
        </article>
      </div>
    </SectionCard>
    <SectionCard id="pitching-evidence" title="Pitching run prevention" subtitle="Point-in-time season results through the last completed game before this matchup">
      <div class="bullpen-visual"><MetricComparison :rows="bullpenComparison" :left-label="game.away.abbr" :right-label="game.home.abbr"/><p>Lower bullpen ERA, runs allowed per game and recent workload are displayed as the stronger relative run-prevention profile. Every value comes from the point-in-time matchup payload.</p></div>
      <div class="pitching-run-grid">
        <article v-for="side in ['away','home']" :key="side" class="pitching-run-card">
          <header><TeamLogo :team="game[side]" :size="42"/><div><small>{{ side.toUpperCase() }} STAFF</small><strong>{{ game[side].name }}</strong></div></header>
          <div class="pitching-run-metrics">
            <span><small>STARTER R / START</small><b class="mono">{{ metric(game.pitchingMatchup?.[side]?.starter_runs_per_start, 2) }}</b><em>{{ game.pitchingMatchup?.[side]?.starter_starts || 0 }} prior starts</em></span>
            <span><small>BULLPEN ERA</small><b class="mono">{{ metric(game.pitchingMatchup?.[side]?.bullpen_era, 2) }}</b><em>{{ metric(game.pitchingMatchup?.[side]?.bullpen_innings, 1) }} IP</em></span>
            <span><small>{{ game.pitchingMatchup?.[side]?.bullpen_runs_basis === 'runs' ? 'BULLPEN R / GAME' : 'BULLPEN ER / GAME' }}</small><b class="mono">{{ metric(game.pitchingMatchup?.[side]?.bullpen_runs_per_game, 2) }}</b><em>{{ game.pitchingMatchup?.[side]?.bullpen_games || 0 }} team games</em></span>
          </div>
          <p><b>{{ game.pitchingMatchup?.[side]?.starter_name || 'Starter pending' }}</b> starter average · bullpen figures exclude starting-pitcher innings.</p>
        </article>
      </div>
    </SectionCard>
    <SectionCard title="Starting pitchers" subtitle="Current season, home/away splits, and each pitcher's five most recent starts">
      <div v-if="game.starterProfiles?.length" class="pitcher-grid">
        <article v-for="starter in game.starterProfiles" :key="starter.id" class="starter">
          <div class="starter-head"><PlayerHeadshot :player="starter" :size="76"/><div><span class="eyebrow" :class="starter.status">{{ starter.status === 'confirmed' ? 'CONFIRMED STARTER' : 'PREDICTED STARTER' }}</span><h3><RouterLink :to="`/players/${starter.id}`">{{ starter.name }}</RouterLink></h3><RouterLink v-if="starter.team_id" class="team-profile-link" :to="`/teams/${starter.team_id}`">{{ starter.team }} · OPEN TEAM PAGE</RouterLink><small v-else>{{ starter.team || starter.position }}</small></div><strong class="era mono">{{ starter.era ?? '—' }}<small>ERA</small></strong></div>
          <div class="stats"><span><small>W–L</small><b class="mono">{{ starter.wins ?? '—' }}–{{ starter.losses ?? '—' }}</b></span><span><small>WHIP</small><b class="mono">{{ starter.whip ?? '—' }}</b></span><span><small>IP</small><b class="mono">{{ starter.innings ?? '—' }}</b></span><span><small>SO / BB</small><b class="mono">{{ starter.strikeouts ?? '—' }} / {{ starter.walks ?? '—' }}</b></span></div>
          <div class="starter-splits">
            <article v-for="venue in ['home','away']" :key="venue">
              <small>{{ venue.toUpperCase() }}</small>
              <template v-if="starter.home_away?.[venue]"><b class="mono">{{ starter.home_away[venue].record }}</b><span>{{ starter.home_away[venue].starts }} GS · {{ starter.home_away[venue].innings }} IP</span><span>{{ starter.home_away[venue].era }} ERA · {{ starter.home_away[venue].whip }} WHIP</span></template>
              <span v-else>No split returned</span>
            </article>
          </div>
          <div class="recent-starts">
            <header><span>LAST 5 STARTS</span><small>IP, hits, runs allowed and workload</small></header>
            <div v-if="starter.recent_starts?.length" class="start-table-wrap">
              <table><thead><tr><th>Date</th><th>Opponent</th><th>Dec</th><th>IP</th><th>H</th><th>R</th><th>ER</th><th>BB</th><th>K</th><th>HR</th><th>P</th></tr></thead><tbody>
                <tr v-for="start in starter.recent_starts" :key="start.game_id || `${start.date}-${start.opponent}`"><td>{{ shortStartDate(start.date) }}</td><td><RouterLink v-if="start.game_id" :to="`/games/${start.game_id}`">{{ startOpponent(start) }}</RouterLink><span v-else>{{ startOpponent(start) }}</span></td><td><b class="decision" :class="start.decision?.toLowerCase() || 'nd'">{{ start.decision || 'ND' }}</b></td><td>{{ start.innings ?? '—' }}</td><td>{{ start.hits ?? '—' }}</td><td>{{ start.runs ?? '—' }}</td><td>{{ start.earned_runs ?? '—' }}</td><td>{{ start.walks ?? '—' }}</td><td>{{ start.strikeouts ?? '—' }}</td><td>{{ start.home_runs ?? '—' }}</td><td>{{ start.pitches ?? '—' }}</td></tr>
              </tbody><tfoot v-if="recentStartAverages(starter.recent_starts)"><tr class="start-average"><td>AVG</td><td>{{ starter.recent_starts.length }} STARTS</td><td>—</td><td>{{ recentStartAverages(starter.recent_starts).innings }}</td><td>{{ recentStartAverages(starter.recent_starts).hits }}</td><td>{{ recentStartAverages(starter.recent_starts).runs }}</td><td>{{ recentStartAverages(starter.recent_starts).earned_runs }}</td><td>{{ recentStartAverages(starter.recent_starts).walks }}</td><td>{{ recentStartAverages(starter.recent_starts).strikeouts }}</td><td>{{ recentStartAverages(starter.recent_starts).home_runs }}</td><td>{{ recentStartAverages(starter.recent_starts).pitches }}</td></tr></tfoot></table>
            </div>
            <p v-else>No completed starts were returned for this season.</p>
          </div>
        </article>
      </div>
      <p v-else class="unavailable">MLB has not announced the probable starting pitchers for this game.</p>
    </SectionCard>
    <MatchupPersonnel v-if="game.modelContext" :game="game" :context="game.modelContext"/>
    <details class="raw-season-data panel"><summary><span><b>RAW OFFICIAL SEASON TOTALS</b><small>AVG, OBP, SLG, OPS, home runs, strikeouts, runs and staff ERA</small></span><em>EXPAND TABLE</em></summary><div class="table-wrap"><table class="data-table"><thead><tr><th>Team</th><th>AVG</th><th>OBP</th><th>SLG</th><th>OPS</th><th>HR</th><th>SO</th><th>Runs</th><th>ERA</th></tr></thead><tbody><tr v-for="row in game.comparison" :key="row.team"><td><b>{{ row.team }}</b></td><td v-for="(value,index) in row.values" :key="index" class="mono">{{ value }}</td></tr></tbody></table></div></details>
    <SectionCard title="Data notice"><div class="ai"><span>◆</span><p>{{ game.dataNotice }}</p></div></SectionCard>
    <SectionCard v-if="game.runProgression?.length > 1" title="This game's run differential by inning"><TrendChart :values="game.runProgression" :labels="game.runProgression.map((_,i)=>i?`Inn ${i}`:'Start')" unit="runs" /></SectionCard>
    <SectionCard v-if="game.odds" title="Current betting markets" subtitle="Prices supplied by The Odds API"><div class="grid-auto"><MetricCard label="Away moneyline" :value="game.odds.awayMoneyline ?? '—'" :delta="game.away.name"/><MetricCard label="Home moneyline" :value="game.odds.homeMoneyline ?? '—'" :delta="game.home.name"/><MetricCard label="Home run line" :value="game.odds.homeSpread ? `${game.odds.homeSpread.point} (${game.odds.homeSpread.price})` : '—'" delta="Current market"/><MetricCard label="Total" :value="game.odds.over ? `${game.odds.over.point} O ${game.odds.over.price}` : '—'" delta="Current market"/></div></SectionCard>
    </template>
  </div>
  <LoadError v-else-if="error" :message="error" @retry="load"/>
  <LoadingState v-else label="Opening matchup intelligence" detail="Loading the official game feed, personnel and current model snapshot."/>
  </div>
</template>

<style scoped>
.totals-market-status{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:12px 14px;border:1px solid color-mix(in srgb,var(--acid) 55%,var(--line));background:color-mix(in srgb,var(--acid) 8%,var(--surface))}.totals-market-status span{display:grid;gap:4px;flex:none}.totals-market-status small{font:700 7px 'DM Mono';letter-spacing:.07em;color:var(--muted)}.totals-market-status b{font-size:12px;color:var(--acid)}.totals-market-status p{margin:0;text-align:right;font:700 9px 'DM Mono';line-height:1.55}.totals-market-status em{display:block;font:500 7px 'DM Mono';font-style:normal;color:var(--muted)}.totals-market-status.unavailable{border-color:var(--line);background:var(--raised)}.totals-market-status.unavailable b{color:var(--orange)}.totals-market-status.unavailable p{max-width:650px;font-family:inherit;font-weight:500;color:var(--muted)}
@media(max-width:650px){.totals-market-status{align-items:flex-start;flex-direction:column}.totals-market-status p{text-align:left}}
</style>

<style scoped>
.league-intelligence{display:grid;gap:22px}.rank-board{display:grid;grid-template-columns:1fr 1fr;gap:12px}.rank-team{--team-color:var(--blue);min-width:0;padding:18px;border:1px solid var(--line);border-top:3px solid var(--team-color);border-radius:16px;background:linear-gradient(145deg,color-mix(in srgb,var(--team-color) 7%,transparent),transparent 42%),var(--raised)}.rank-team.home{--team-color:var(--acid)}.rank-team>header{display:flex;align-items:center;gap:11px;padding-bottom:14px;border-bottom:1px solid var(--line)}.rank-team>header div{display:grid;gap:3px;min-width:0}.rank-team>header small{font:700 8px 'DM Mono';letter-spacing:.08em;color:var(--muted)}.rank-team>header h3{margin:0;font-size:17px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rank-team>header>span{margin-left:auto;padding:6px 8px;border:1px solid var(--line);font:700 8px 'DM Mono';color:var(--muted);white-space:nowrap}.rank-team>p{min-height:34px;margin:12px 0 15px;font-size:10px;line-height:1.65;color:var(--muted)}.rank-team>section+section{margin-top:16px}.rank-group-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}.rank-group-title b,.rank-group-title small{font:800 8px 'DM Mono';letter-spacing:.08em}.rank-group-title b{color:var(--team-color)}.rank-group-title small{color:var(--muted)}.rank-row{display:grid;grid-template-columns:minmax(150px,1.2fr) minmax(70px,.8fr) 76px;gap:11px;align-items:center;min-height:57px;padding:8px 0;border-top:1px solid var(--line)}.rank-row>span{display:grid;gap:4px;min-width:0}.rank-row>span b{font-size:11px}.rank-row>span small{font-size:8px;line-height:1.35;color:var(--muted)}.rank-row>i{height:6px;overflow:hidden;border-radius:99px;background:var(--panel)}.rank-row>i em{display:block;height:100%;min-width:4px;border-radius:99px;background:var(--team-color);transition:width .7s cubic-bezier(.22,.8,.3,1)}.rank-row>strong{display:grid;justify-items:end;font-size:19px;line-height:1;color:var(--text)}.rank-row>strong small{margin-top:5px;font:800 6px 'DM Mono';letter-spacing:.06em;color:var(--muted)}.rank-row.elite>strong,.rank-row.elite>strong small{color:var(--acid)}.rank-row.concern>strong,.rank-row.concern>strong small{color:var(--orange)}.inning-intro{display:flex;align-items:end;justify-content:space-between;gap:24px;padding-top:5px}.inning-intro h3{margin:6px 0 0;font-size:24px;letter-spacing:-.04em}.inning-intro p{max-width:560px;margin:0;font-size:9px;line-height:1.65;color:var(--muted)}.inning-chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.inning-chart-grid>article{min-width:0;padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--surface)}.inning-chart-grid>article>header{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:10px}.inning-chart-grid header div{display:grid;gap:4px}.inning-chart-grid header small,.inning-chart-grid header>span{font:700 7px 'DM Mono';letter-spacing:.07em;color:var(--muted)}.inning-chart-grid header b{font-size:14px}.phase-board{display:grid;grid-template-columns:1fr 1fr;gap:12px}.phase-board>article{--team-color:var(--blue);padding:15px;border:1px solid var(--line);border-radius:14px;background:var(--raised)}.phase-board>article.home{--team-color:var(--acid)}.phase-board article>header{display:flex;align-items:center;gap:9px;padding-bottom:11px;border-bottom:1px solid var(--line)}.phase-board article>header div{display:grid;gap:3px}.phase-board article>header small{font:700 7px 'DM Mono';letter-spacing:.07em;color:var(--muted)}.phase-board article>header b{font-size:11px}.phase-board article>div{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:9px}.phase-board article>div span{display:grid;align-content:start;gap:5px;min-width:0;padding:11px;background:var(--panel);border-radius:9px}.phase-board article>div small{font:700 7px 'DM Mono';color:var(--team-color)}.phase-board article>div b{font-size:10px;line-height:1.45}.phase-board article>div em{font-size:7px;line-height:1.45;font-style:normal;color:var(--muted)}.phase-board footer{display:flex;gap:18px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line);font-size:8px;color:var(--muted)}.phase-board footer b{color:var(--text)}.league-source{margin:0;padding-top:13px;border-top:1px solid var(--line);font-size:8px;line-height:1.6;color:var(--muted)}.raw-season-data{overflow:hidden}.raw-season-data>summary{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:64px;padding:13px 17px;cursor:pointer;list-style:none}.raw-season-data>summary::-webkit-details-marker{display:none}.raw-season-data>summary span{display:grid;gap:5px}.raw-season-data>summary b,.raw-season-data>summary em{font:800 8px 'DM Mono';letter-spacing:.07em}.raw-season-data>summary small{font-size:8px;color:var(--muted)}.raw-season-data>summary em{font-style:normal;color:var(--acid)}.raw-season-data[open]>summary{border-bottom:1px solid var(--line)}.raw-season-data .table-wrap{padding:12px}
@media(max-width:1050px){.rank-board,.inning-chart-grid,.phase-board{grid-template-columns:1fr}.inning-intro{align-items:flex-start;flex-direction:column}.inning-intro p{max-width:760px}}
@media(max-width:620px){.rank-team{padding:13px}.rank-row{grid-template-columns:minmax(130px,1fr) 62px}.rank-row>i{display:none}.phase-board article>div{grid-template-columns:1fr}.phase-board footer{flex-direction:column;gap:6px}.inning-chart-grid>article{padding:11px}.inning-intro h3{font-size:20px}}
</style>
<style scoped>
.opening-verdict{display:grid;grid-template-columns:.8fr 1.15fr .8fr;gap:1px;padding:0;overflow:hidden;background:var(--line);border-top:4px solid var(--acid);border-radius:18px}.opening-verdict>div{min-height:280px;padding:21px;background:var(--surface)}.verdict-pick{position:relative;display:flex;flex-direction:column}.verdict-pick h2{margin:9px 0 5px;font-size:28px;letter-spacing:-.05em}.verdict-pick>p{max-width:260px;margin:0;color:var(--muted);font-size:9px;line-height:1.55}.verdict-pick>p b{color:var(--text)}.verdict-pick :deep(.prob-ring){position:absolute;right:5px;bottom:-15px}.verdict-score{display:flex;flex-direction:column}.verdict-score>strong{margin-top:12px;font:800 34px 'DM Mono';color:var(--acid)}.verdict-score>p{margin:4px 0 16px;color:var(--muted);font-size:8px}.verdict-score>div{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:auto}.verdict-score a{min-width:0;padding:8px;display:flex;align-items:center;gap:8px;background:var(--raised);color:var(--text);text-decoration:none}.verdict-score a>span{min-width:0;display:flex;flex-direction:column;gap:3px}.verdict-score a small{font:700 6px 'DM Mono';color:var(--muted)}.verdict-score a b{font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.verdict-score a em{font:600 6px 'DM Mono';font-style:normal;color:var(--acid)}.verdict-signals{display:grid!important;gap:1px!important;padding:0!important;background:var(--line)!important}.verdict-signals article{padding:18px;display:flex;flex-direction:column;background:color-mix(in srgb,var(--acid) 5%,var(--surface))}.verdict-signals article.risk{background:color-mix(in srgb,var(--orange) 5%,var(--surface))}.verdict-signals span{font:800 7px 'DM Mono';color:var(--acid)}.verdict-signals .risk span{color:var(--orange)}.verdict-signals b{margin:auto 0 5px;font-size:15px}.verdict-signals p{margin:0;color:var(--muted);font-size:8px;line-height:1.5}.pitcher-visual{display:grid;grid-template-columns:1fr 330px;gap:28px;align-items:center}.pitcher-identities{display:grid;gap:7px}.pitcher-identities a{padding:10px;display:flex;align-items:center;gap:11px;border:1px solid var(--line);background:var(--raised);color:var(--text);text-decoration:none}.pitcher-identities a>span{display:flex;flex-direction:column;gap:4px}.pitcher-identities small,.pitcher-identities em{font:700 6px 'DM Mono';font-style:normal;color:var(--muted)}.pitcher-identities em{color:var(--acid)}.pitcher-identities b{font-size:11px}.offense-visual{display:grid;grid-template-columns:.8fr 1.2fr;gap:30px;align-items:center}.offense-visual>div>header{display:grid;gap:5px;margin-bottom:10px}.offense-visual>div>header b{font-size:14px}.offense-visual>div>p{margin:5px 0 0;color:var(--muted);font-size:8px;line-height:1.55}.bullpen-visual{display:grid;grid-template-columns:1fr 320px;gap:30px;align-items:center;margin-bottom:15px;padding:16px;border:1px solid var(--line);background:var(--surface)}.bullpen-visual>p{margin:0;color:var(--muted);font-size:9px;line-height:1.65}.starter-head h3 a{color:var(--text);text-decoration:none}.starter-head h3 a:hover{text-decoration:underline;text-decoration-color:var(--acid)}
.matchup-team h2 a{color:var(--text);text-decoration:none}.matchup-team h2 a:hover{text-decoration:underline;text-decoration-color:var(--acid)}.team-profile-link{display:block;width:max-content;max-width:100%;margin-top:5px;color:var(--acid);font:700 7px 'DM Mono';text-decoration:none}.team-profile-link:hover{text-decoration:underline;text-underline-offset:3px}
@media(max-width:1050px){.opening-verdict{grid-template-columns:1fr 1fr}.verdict-signals{grid-column:1/-1;grid-template-columns:1fr 1fr!important}.pitcher-visual,.offense-visual{grid-template-columns:1fr}.pitcher-identities{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.opening-verdict{grid-template-columns:1fr}.verdict-signals{grid-column:auto;grid-template-columns:1fr!important}.verdict-pick :deep(.prob-ring){position:relative;right:auto;bottom:auto;align-self:center;margin-top:5px}.verdict-score>div,.pitcher-identities{grid-template-columns:1fr}.bullpen-visual{grid-template-columns:1fr}}
</style>

<style scoped>
.matchup-index{position:sticky;top:68px;z-index:12;display:flex;align-items:center;gap:4px;min-width:0;padding:7px;border:1px solid var(--line);background:color-mix(in srgb,var(--surface) 92%,transparent);backdrop-filter:blur(14px)}.matchup-index span{padding:0 8px;font:800 6px 'DM Mono';color:var(--muted)}.matchup-index a{min-width:0;padding:8px 11px;background:var(--raised);color:var(--text);text-decoration:none;font:800 7px 'DM Mono';white-space:nowrap}.matchup-index a:hover{background:var(--selection-bg);color:var(--selection-text)}.deep-evidence{border:1px solid var(--line);background:var(--surface)}.deep-evidence>summary{min-height:62px;padding:12px 15px;display:flex;align-items:center;justify-content:space-between;gap:15px;cursor:pointer;list-style:none}.deep-evidence>summary::-webkit-details-marker{display:none}.deep-evidence>summary span{display:grid;gap:4px}.deep-evidence>summary b,.deep-evidence>summary em{font:800 8px 'DM Mono'}.deep-evidence>summary small{font-size:8px;color:var(--muted)}.deep-evidence>summary em{font-style:normal;color:var(--acid)}.deep-evidence[open]>summary{border-bottom:1px solid var(--line)}.deep-evidence>.projection-reasoning{border:0;border-radius:0}@media(max-width:700px){.matchup-index{top:58px;overflow-x:auto}.matchup-index span{display:none}.matchup-index a{font-size:6px;padding:8px}}
.game-page{display:grid;min-width:0}
.totals-projection{display:grid;gap:14px}.totals-call{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:1px;background:var(--line);border:1px solid var(--line)}.totals-call>span,.totals-call>div{padding:17px;background:var(--raised);display:flex;flex-direction:column;gap:6px}.totals-call>div{background:var(--contrast);color:var(--on-contrast)}.totals-call small{font:600 7px 'DM Mono';letter-spacing:.08em;color:var(--muted)}.totals-call strong{font-size:21px;color:var(--acid)}.totals-call>div strong{font-size:28px;color:var(--accent)}.totals-call em{font-size:8px;line-height:1.5;color:var(--muted);font-style:normal}.total-thresholds{display:grid;grid-template-columns:repeat(6,1fr);gap:6px}.total-thresholds article{padding:11px;border:1px solid var(--line);background:var(--raised)}.total-thresholds article.recommended{border-color:var(--acid);box-shadow:inset 0 -3px var(--acid)}.total-thresholds small{font:700 7px 'DM Mono';color:var(--muted)}.total-thresholds div{display:grid;gap:5px;margin-top:8px}.total-thresholds span{display:flex;justify-content:space-between;font-size:8px}.total-reasons{padding:15px;border:1px solid var(--line);background:var(--surface)}.total-reasons header{display:flex;justify-content:space-between;gap:20px;align-items:center}.total-reasons header p{max-width:620px;margin:0;font-size:8px;color:var(--muted);line-height:1.55}.total-reasons>div{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:12px}.total-reasons article{display:grid;gap:5px;padding:10px;background:var(--raised)}.total-reasons article>span{justify-self:start;padding:4px 6px;font:700 7px 'DM Mono';background:color-mix(in srgb,var(--acid) 20%,var(--surface));color:var(--acid)}.total-reasons article>span.under{background:color-mix(in srgb,var(--blue) 20%,var(--surface));color:var(--blue)}.total-reasons b{font-size:10px}.total-reasons small{font-size:8px;color:var(--muted)}@media(max-width:850px){.totals-call{grid-template-columns:1fr}.total-thresholds{grid-template-columns:repeat(3,1fr)}.total-reasons>div{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.total-thresholds{grid-template-columns:repeat(2,1fr)}.total-reasons>div{grid-template-columns:1fr}}
.return-builder{margin-top:16px;padding:10px 13px;border:1px solid var(--line);background:var(--surface);display:flex;align-items:center;justify-content:space-between;gap:12px}.return-builder a{height:36px;padding:0 13px;background:var(--ink);color:var(--paper);display:flex;align-items:center;gap:8px;text-decoration:none;font:700 8px 'DM Mono';letter-spacing:.06em}.return-builder svg{width:15px}.return-builder span{font:500 8px 'DM Mono';color:var(--muted)}
.projection{display:grid;gap:14px}.probability-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:14px}.probability-row>div{display:flex;align-items:center;gap:11px}.probability-row span{display:flex;flex-direction:column}.probability-row small{font-size:8px;color:var(--muted)}.probability-row strong{font-size:27px;color:var(--acid);margin-top:3px}.probability-row .home-prob{justify-content:flex-end;text-align:right}.model-pick{flex-direction:column;text-align:center!important;gap:3px!important}.model-pick b{font-size:13px}.model-pick span{font-size:8px;color:var(--muted)}.probability-bar{height:8px;display:flex;border-radius:5px;overflow:hidden;background:var(--panel)}.probability-bar i:first-child{background:#613f75}.probability-bar i:last-child{background:var(--acid)}.reason-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.reason-grid article{display:flex;align-items:center;gap:11px;min-height:56px;padding:10px 12px;background:var(--raised);border:1px solid var(--line);border-left-width:3px;border-radius:6px}.reason-grid article.home{border-left-color:var(--acid)}.reason-grid article.away{border-left-color:var(--blue)}.reason-grid article>span{min-width:50px;padding:7px 6px;text-align:center;border:1px solid color-mix(in srgb,var(--acid) 60%,var(--line));border-radius:99px;background:color-mix(in srgb,var(--acid) 20%,var(--surface));font:800 10px 'DM Mono';letter-spacing:.04em;color:var(--text)}.reason-grid article>span.away{border-color:color-mix(in srgb,var(--blue) 65%,var(--line));background:color-mix(in srgb,var(--blue) 22%,var(--surface));color:var(--text)}.reason-grid article div{display:flex;flex-direction:column}.reason-grid b{font-size:11px}.reason-grid small{font-size:8px;color:var(--muted);margin-top:4px;text-transform:capitalize}.model-audit{display:flex;gap:20px;padding-top:11px;border-top:1px solid var(--line);font-size:8px;color:var(--muted)}.model-audit b{color:var(--text);margin-left:4px}
.projection-reasoning{display:grid;gap:13px;padding:18px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(135deg,color-mix(in srgb,var(--acid) 5%,transparent),transparent 45%),var(--surface)}.projection-reasoning>header{display:flex;align-items:end;justify-content:space-between;gap:15px;padding-bottom:12px;border-bottom:1px solid var(--line)}.projection-reasoning h3{font-size:21px;letter-spacing:-.035em;margin:5px 0 0}.reasoning-live{--state:var(--acid);display:flex;align-items:center;gap:7px;padding:7px 9px;border:1px solid color-mix(in srgb,var(--state) 50%,var(--line));color:var(--state);font:700 7px 'DM Mono';letter-spacing:.06em;white-space:nowrap}.reasoning-live i{width:6px;height:6px;border-radius:50%;background:var(--state);box-shadow:0 0 10px color-mix(in srgb,var(--state) 55%,transparent)}.reasoning-live.syncing{--state:var(--blue)}.reasoning-live.aging{--state:#e3a73f}.reasoning-live.stale{--state:var(--orange)}.reasoning-summary{margin:0;font-size:11px;line-height:1.7;color:var(--text)}.projection-reasoning .reason-grid article{align-items:flex-start;min-height:112px;padding:13px}.projection-reasoning .reason-grid article.counter{opacity:.86}.projection-reasoning .reason-grid article div{gap:4px}.projection-reasoning .reason-grid small{margin:0;font:700 7px 'DM Mono';letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}.projection-reasoning .reason-grid b{font-size:12px}.projection-reasoning .reason-grid p{margin:2px 0 0;font-size:9px;line-height:1.55;color:var(--muted)}.projection-reasoning .reason-grid p strong{font-size:inherit;color:var(--text)}.reasoning-status{display:grid;grid-template-columns:1fr 1fr;gap:8px}.reasoning-status>div{display:flex;flex-direction:column;gap:5px;padding:12px;background:var(--raised);border-radius:9px}.reasoning-status small{font:700 7px 'DM Mono';letter-spacing:.07em;color:var(--muted)}.reasoning-status b{font-size:10px}.reasoning-status span{font-size:8px;line-height:1.45;color:var(--muted)}.projection-reasoning>aside{padding-top:10px;border-top:1px solid var(--line);font-size:8px;line-height:1.6;color:var(--muted)}
@media(max-width:700px){.projection-reasoning>header{align-items:flex-start;flex-direction:column}.reasoning-status{grid-template-columns:1fr}.projection-reasoning{padding:14px}}
.final-review{display:grid;grid-template-columns:1fr 1fr;gap:8px}.final-review>div{display:grid;gap:5px;padding:14px 16px;border:1px solid var(--line);border-radius:11px;background:var(--raised)}.final-review small{font:7px 'DM Mono';color:var(--muted)}.final-review strong{font-size:22px}.final-review b{font:800 11px 'DM Mono'}.final-review span{font-size:8px;color:var(--muted)}.final-review .correct{color:var(--acid)}.final-review .missed{color:var(--orange)}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.form-team{padding:14px;background:var(--raised);border-radius:8px}.form-team header{display:flex;align-items:center;gap:10px;padding-bottom:11px;border-bottom:1px solid var(--line)}.form-team header>div{display:flex;flex-direction:column}.form-team header strong{font-size:12px}.form-team header small{font-size:8px;color:var(--muted);margin-top:3px}.form-record{margin-left:auto;color:var(--acid);font-size:15px}.form-row{display:grid;grid-template-columns:25px minmax(0,1fr) auto;align-items:center;gap:9px;padding:10px 2px;border-bottom:1px solid var(--line);text-decoration:none}.form-row i{width:22px;height:22px;display:grid;place-items:center;border-radius:5px;font:800 9px 'DM Mono';font-style:normal}.form-row i.win{background:rgba(65,234,212,.16);color:var(--acid)}.form-row i.loss{background:rgba(255,32,110,.14);color:#ff78a6}.form-row span{display:flex;flex-direction:column;min-width:0}.form-row b{font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.form-row small{font-size:8px;color:var(--muted);margin-top:3px}.form-row>strong{font-size:12px;color:var(--text)}
.starter{background:var(--raised);padding:14px;border-radius:7px}.starter-head{display:flex;align-items:center;gap:13px;margin-bottom:13px}.starter-head h3{margin:4px 0 3px}.starter-head>div{min-width:0}.starter-head>div small{color:var(--muted);font-size:9px}.era{margin-left:auto;color:var(--acid);font-size:25px;text-align:right}.era small{display:block;color:var(--muted);font-size:8px}.unavailable{color:var(--muted);font-size:11px;margin:0}
.starter-splits{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}.starter-splits article{display:grid;grid-template-columns:auto 1fr;gap:3px 9px;padding:10px;border:1px solid var(--line);background:var(--panel)}.starter-splits small{grid-row:1/4;align-self:center;font:800 7px 'DM Mono';letter-spacing:.08em;color:var(--muted);writing-mode:vertical-rl;transform:rotate(180deg)}.starter-splits b{font-size:15px;color:var(--acid)}.starter-splits span{font:600 7px 'DM Mono';color:var(--muted)}.recent-starts{margin-top:12px}.recent-starts>header{display:flex;align-items:end;justify-content:space-between;gap:10px;margin-bottom:7px}.recent-starts>header span{font:800 8px 'DM Mono';letter-spacing:.08em}.recent-starts>header small{font-size:7px;color:var(--muted)}.start-table-wrap{overflow-x:auto;border:1px solid var(--line)}.recent-starts table{width:100%;min-width:530px;border-collapse:collapse;background:var(--panel);font:600 7px 'DM Mono'}.recent-starts th,.recent-starts td{padding:7px 5px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}.recent-starts th{font-size:6px;text-transform:uppercase;color:var(--muted);background:var(--surface)}.recent-starts th:first-child,.recent-starts td:first-child,.recent-starts th:nth-child(2),.recent-starts td:nth-child(2){text-align:left}.recent-starts tbody tr:last-child td{border-bottom:0}.recent-starts tfoot td{border-top:2px solid color-mix(in srgb,var(--acid) 55%,var(--line));border-bottom:0;background:color-mix(in srgb,var(--acid) 8%,var(--surface));color:var(--acid);font-weight:800}.recent-starts tfoot td:nth-child(2){color:var(--muted);font-size:6px;letter-spacing:.05em}.recent-starts a{color:var(--text);text-decoration:none}.recent-starts a:hover{text-decoration:underline}.recent-starts p{margin:0;padding:12px;background:var(--panel);font-size:8px;color:var(--muted)}.decision{display:inline-grid;min-width:20px;height:20px;place-items:center;border-radius:4px;background:var(--raised);font-size:7px}.decision.w{color:var(--acid)}.decision.l{color:var(--orange)}.decision.nd{color:var(--muted)}
.view{display:grid;gap:14px}.match{padding:22px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:20px;background:radial-gradient(circle at 80%,rgba(97,63,117,.25),transparent 30%),var(--panel)}.matchup-team{display:flex;align-items:center;gap:14px;min-width:0}.matchup-team.home{text-align:right;justify-content:flex-end}.matchup-team h2{font-size:22px;margin:5px 0;line-height:1.1}.match-meta{text-align:center}.match-meta strong{display:block;font:800 26px 'DM Mono';margin:7px 0}.match-meta p{font-size:10px;color:var(--muted);margin:0}.prob{grid-column:1/-1;max-width:340px;width:100%;justify-self:center;text-align:center}.prob small{font-size:9px}.prob>strong{display:block;font-size:24px;color:var(--acid);margin:6px 0}.two{display:grid;grid-template-columns:2fr 1fr;gap:14px}.pitcher-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.pitcher-grid>div{background:var(--raised);padding:14px;border-radius:7px}.pitcher-grid h3{margin:0 0 12px;font-size:13px}.pitcher-grid h3 small{color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}.stats span{padding:8px;background:var(--panel);display:flex;flex-direction:column}.stats small{font-size:8px;color:var(--muted);text-transform:uppercase}.stats b{font-size:12px;margin-top:4px}.pitchmix{height:28px;display:flex;margin-top:13px;overflow:hidden;border-radius:3px}.pitchmix i{background:var(--acid);color:#04201b;display:grid;place-items:center;font-style:normal;border-right:1px solid #07111f}.pitchmix i:nth-child(even){background:#613f75;color:white}.pitchmix small{font-size:7px}.bull{margin:15px 0}.bull>div{display:flex;justify-content:space-between;font-size:11px}.bull p{font-size:9px;color:var(--muted)}.ai{display:flex;gap:15px}.ai>span{color:var(--acid);font-size:28px}.ai p{font-size:12px;line-height:1.7;margin:0}.load{padding:50px;text-align:center}@media(max-width:850px){.match{grid-template-columns:1fr 1fr}.match-meta{grid-column:1/-1;grid-row:2}.prob{grid-row:3}.two{grid-template-columns:1fr}.pitcher-grid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.matchup-team h2{font-size:17px}}@media(max-width:520px){.match{padding:15px;gap:10px}.matchup-team{flex-direction:column;align-items:flex-start}.matchup-team.home{flex-direction:column-reverse;align-items:flex-end}.matchup-team h2{font-size:14px}.match-meta p{font-size:9px}}
@media(max-width:850px){.form-grid{grid-template-columns:1fr}.reason-grid{grid-template-columns:1fr}.model-audit{flex-wrap:wrap}.probability-row{grid-template-columns:1fr 1fr}.model-pick{grid-column:1/-1;grid-row:2}}
@media(max-width:650px){.final-review{grid-template-columns:1fr}}
.context-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.context-grid article,.context-alerts article{display:flex;flex-direction:column;gap:4px;padding:10px;background:var(--raised);border:1px solid var(--line);border-radius:6px}.context-grid b{font-size:11px}.context-grid span,.context-alerts span{font-size:9px;color:var(--muted)}.context-alerts{display:grid;gap:6px}.context-alerts article.warning{border-color:#dbad45}.context-alerts article.critical{border-color:var(--orange)}.context-alerts b{text-transform:uppercase;font-size:8px;color:#ffd27a}
.confidence-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.confidence-summary>div{padding:11px;background:linear-gradient(135deg,rgba(65,234,212,.08),transparent),var(--raised);border:1px solid var(--line);border-radius:6px;display:flex;flex-direction:column;gap:5px}.confidence-summary small{font-size:8px;color:var(--muted)}.confidence-summary strong{font-size:15px;color:var(--acid)}.confidence-summary em{font:800 8px 'DM Mono';font-style:normal;padding:4px 6px;border-radius:10px;background:rgba(255,255,255,.08);vertical-align:middle}.confidence-summary em.high{color:var(--acid)}.confidence-summary em.moderate{color:#ffd27a}.confidence-summary em.low{color:#ff8bac}.confidence-summary p{font-size:8px;color:var(--muted);margin:0;line-height:1.45}
@media(max-width:850px){.context-grid{grid-template-columns:1fr}}
@media(max-width:850px){.confidence-summary{grid-template-columns:1fr}}
.confidence-summary{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.input-state{width:max-content;padding:4px 7px;border-radius:99px;font:500 7px 'DM Mono';letter-spacing:.08em}.input-state.confirmed,.eyebrow.confirmed{color:var(--acid)!important;background:color-mix(in srgb,var(--acid) 10%,transparent)}.input-state.predicted,.eyebrow.predicted{color:var(--blue)!important;background:color-mix(in srgb,var(--blue) 10%,transparent)}.input-state.pending{color:var(--muted)}
.match{background:radial-gradient(circle at 80%,color-mix(in srgb,var(--acid) 9%,transparent),transparent 32%),var(--panel);border-radius:22px}.prob>strong,.era,.probability-row strong,.form-record,.ai>span{color:var(--acid)}.probability-bar i:first-child{background:var(--blue)}.probability-bar i:last-child{background:var(--acid)}.starter,.form-team,.reason-grid article,.context-grid article{border-radius:13px}.starter-head .eyebrow{padding:4px 7px;border-radius:99px}.confidence-summary>div{background:linear-gradient(135deg,color-mix(in srgb,var(--acid) 6%,transparent),transparent),var(--raised);border-radius:12px}.confidence-summary strong{color:var(--acid)}
.prob{max-width:520px}.view{grid-template-columns:minmax(0,1fr);min-width:0}.view>*{min-width:0}.match{min-width:0;overflow:hidden}.matchup-team>div{min-width:0}.matchup-team h2{overflow-wrap:anywhere}@media(max-width:850px){.match{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.detail-load{display:flex;align-items:center;justify-content:center;gap:13px}.detail-load div{display:flex;flex-direction:column;text-align:left;gap:4px}.detail-load b{font-size:12px}.detail-load small{font-size:9px;color:var(--muted)}.load-pulse{width:11px;height:11px;border-radius:50%;background:var(--acid);animation:pulse-load 1.2s infinite}@keyframes pulse-load{50%{opacity:.25;transform:scale(.75)}}
.prob>p{display:none}.projection-stamp{--freshness:var(--acid);min-height:54px;display:grid;grid-template-columns:3px auto 1fr;align-items:center;gap:12px;padding:9px 14px;border-radius:0}.projection-stamp>i{width:3px;height:28px;background:var(--freshness);box-shadow:0 0 14px color-mix(in srgb,var(--freshness) 45%,transparent)}.projection-stamp>span{display:flex;flex-direction:column;gap:4px}.projection-stamp small{font:500 7px 'DM Mono';letter-spacing:.11em;color:var(--muted)}.projection-stamp b{font-size:10px}.projection-stamp em{justify-self:end;padding:6px 9px;border:1px solid color-mix(in srgb,var(--freshness) 55%,var(--line));background:color-mix(in srgb,var(--freshness) 10%,var(--surface));color:var(--freshness);font:700 7px 'DM Mono';font-style:normal;letter-spacing:.07em}.projection-stamp.syncing{--freshness:var(--blue)}.projection-stamp.aging{--freshness:#e3a73f}.projection-stamp.stale{--freshness:var(--orange)}.projection-stamp.locked{--freshness:var(--muted)}@media(max-width:520px){.projection-stamp{grid-template-columns:3px 1fr}.projection-stamp em{grid-column:2;justify-self:start}}
.probability-bar i{transition:width .65s cubic-bezier(.22,.8,.3,1)}
.pitching-run-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pitching-run-card{padding:15px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(135deg,color-mix(in srgb,var(--blue) 7%,transparent),transparent 48%),var(--raised)}.pitching-run-card>header{display:flex;align-items:center;gap:10px;padding-bottom:11px;border-bottom:1px solid var(--line)}.pitching-run-card>header div{display:flex;flex-direction:column;gap:3px}.pitching-run-card>header small{font:700 7px 'DM Mono';letter-spacing:.08em;color:var(--muted)}.pitching-run-card>header strong{font-size:12px}.pitching-run-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.pitching-run-metrics span{display:flex;min-width:0;flex-direction:column;gap:5px;padding:10px;background:var(--panel);border-radius:9px}.pitching-run-metrics small{font:700 7px 'DM Mono';line-height:1.35;color:var(--muted)}.pitching-run-metrics b{font-size:20px;color:var(--acid)}.pitching-run-metrics em{font:500 7px 'DM Mono';font-style:normal;color:var(--muted)}.pitching-run-card>p{margin:10px 1px 0;font-size:8px;line-height:1.5;color:var(--muted)}.pitching-run-card>p b{color:var(--text)}@media(max-width:850px){.pitching-run-grid{grid-template-columns:1fr}}@media(max-width:460px){.pitching-run-metrics{grid-template-columns:1fr}.pitching-run-metrics span{display:grid;grid-template-columns:1fr auto;align-items:center}.pitching-run-metrics em{grid-column:1/-1}.pitching-run-metrics b{grid-column:2;grid-row:1/3}}
</style>
