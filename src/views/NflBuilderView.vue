<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, Check, ChevronRight, CircleGauge, Layers3, LockKeyhole, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-vue-next'
import { api } from '../services/api'

const loading = ref(true)
const error = ref('')
const payload = ref(null)
const marketMode = ref('moneyline')
const evidenceMode = ref('shadow')
const selectedWeek = ref('')
const target = ref(5)
const minimumOdds = ref('all')
const selected = ref([])

const allScheduled = computed(() => (payload.value?.items || []).filter(game => game.status === 'Scheduled' && game.prediction))
const weekNumber = game => String(game.round || '').match(/WEEK\s+(\d+)/i)?.[1] || '—'
const availableWeeks = computed(() => [...new Set(allScheduled.value.map(weekNumber))].sort((a, b) => Number(a) - Number(b)))
const scheduled = computed(() => allScheduled.value.filter(game => selectedWeek.value === 'all' || weekNumber(game) === selectedWeek.value))
const marketDefinitions = prediction => {
  const line = Number(prediction.total_line)
  const spread = Number(prediction.spread_line)
  const values = []
  const homeMoneyline = Number(prediction.markets?.home_win || 0), awayMoneyline = Number(prediction.markets?.away_win || 0)
  values.push({
    market: 'moneyline', side: homeMoneyline >= awayMoneyline ? 'home' : 'away',
    probability: Math.max(homeMoneyline, awayMoneyline),
    odds: Number(homeMoneyline >= awayMoneyline ? prediction.prices?.home_moneyline : prediction.prices?.away_moneyline) || null,
    eligible: prediction.market_eligibility?.moneyline === true,
    consensus: prediction.model_consensus?.moneyline !== false,
  })
  if (Number.isFinite(spread) && prediction.markets?.home_spread != null) {
    const home = Number(prediction.markets.home_spread), away = Number(prediction.markets.away_spread)
    values.push({ market: 'spread', side: home >= away ? 'home' : 'away', line: spread,
      probability: Math.max(home, away), odds: Number(home >= away ? prediction.prices?.home_spread : prediction.prices?.away_spread) || null,
      eligible: prediction.market_eligibility?.spread === true, consensus: true })
  }
  if (Number.isFinite(line) && prediction.markets?.over_total != null) {
    const over = Number(prediction.markets.over_total), under = Number(prediction.markets.under_total)
    values.push({ market: 'total', side: over >= under ? 'over' : 'under', line,
      probability: Math.max(over, under), odds: Number(over >= under ? prediction.prices?.over_total : prediction.prices?.under_total) || null,
      eligible: prediction.market_eligibility?.total === true, consensus: true })
  }
  return values
}
const allCandidates = computed(() => scheduled.value.flatMap(game => marketDefinitions(game.prediction).map(option => ({
  id: `${game.id}:${option.market}:${option.side}`, game, option,
}))))
const candidates = computed(() => allCandidates.value
  .filter(row => marketMode.value === 'mixed' || row.option.market === marketMode.value)
  .filter(row => evidenceMode.value !== 'production' || row.option.eligible)
  .filter(row => minimumOdds.value === 'all' || (row.option.odds && row.option.odds >= Number(minimumOdds.value)))
  .sort((a, b) => b.option.probability - a.option.probability))
const selectedIds = computed(() => new Set(selected.value.map(row => row.id)))
const occupied = computed(() => new Set(selected.value.map(row => String(row.game.id))))
const jointProbability = computed(() => selected.value.reduce((product, row) => product * row.option.probability, 1))
const combinedOdds = computed(() => selected.value.length && selected.value.every(row => row.option.odds)
  ? selected.value.reduce((product, row) => product * row.option.odds, 1) : null)
const readiness = computed(() => scheduled.value[0]?.prediction?.readiness || {})

const teamName = (game, side) => game[side]?.name || side
const selectionLabel = row => {
  const { game, option } = row
  if (option.market === 'moneyline') return `${teamName(game, option.side)} moneyline`
  if (option.market === 'total') return `${option.side.toUpperCase()} ${option.line}`
  const displayed = option.side === 'home' ? -Number(option.line) : Number(option.line)
  return `${teamName(game, option.side)} ${displayed > 0 ? '+' : ''}${displayed}`
}
const marketLabel = market => ({ moneyline: 'Moneyline', spread: 'Spread', total: 'Total points' }[market] || market)
const formatProbability = value => `${(Number(value || 0) * 100).toFixed(1)}%`
const eventLabel = game => `${game.away?.name} @ ${game.home?.name}`
const scoreLabel = game => {
  const score = game.prediction?.expected_score
  return score ? `${game.away?.name} ${Number(score.away).toFixed(1)} — ${Number(score.home).toFixed(1)} ${game.home?.name}` : 'Score distribution pending'
}
const toggle = row => {
  if (selectedIds.value.has(row.id)) { selected.value = selected.value.filter(item => item.id !== row.id); return }
  if (occupied.value.has(String(row.game.id)) || selected.value.length >= Number(target.value)) return
  selected.value = [...selected.value, row]
}
const buildBest = () => {
  const picks = [], games = new Set(), exposure = new Map()
  const maximumRepeatedDirection = marketMode.value === 'mixed' ? (Number(target.value) <= 5 ? 2 : 3) : Number(target.value)
  for (const row of candidates.value) {
    const gameId = String(row.game.id)
    const key = `${row.option.market}:${row.option.side}`
    if (games.has(gameId) || (exposure.get(key) || 0) >= maximumRepeatedDirection) continue
    if (row.option.market === 'moneyline' && !row.option.consensus) continue
    picks.push(row); games.add(gameId); exposure.set(key, (exposure.get(key) || 0) + 1)
    if (picks.length >= Number(target.value)) break
  }
  selected.value = picks
}
const load = async () => {
  loading.value = true; error.value = ''
  try {
    payload.value = await api.sportDirectory('american-football', 'games', { season: new Date().getUTCFullYear() })
    const weeks = availableWeeks.value
    if (!selectedWeek.value || (selectedWeek.value !== 'all' && !weeks.includes(selectedWeek.value))) selectedWeek.value = weeks[0] || 'all'
  }
  catch (caught) { error.value = caught?.message || 'NFL slate could not be loaded.' }
  finally { loading.value = false }
}
watch([marketMode, evidenceMode, selectedWeek, minimumOdds, target], () => { selected.value = [] })
onMounted(load)
</script>

<template>
  <div class="nfl-builder">
    <section class="hero">
      <div><span class="eyebrow">NINTH / NFL BUILDER</span><h1>Build from<br><i>the distribution.</i></h1><p>One NFL-native card surface for moneyline, spread and totals. Every probability is generated before the result, current lines are used only as decision thresholds, and each market unlocks independently.</p></div>
      <aside><ShieldCheck/><span>RELEASE STATE</span><b>Moneyline is historically ready.</b><p>Spread and totals remain shadow-only after failing their untouched line-aware audit. All markets continue collecting immutable live observations.</p><RouterLink to="/american-football/models">OPEN MODEL EVIDENCE <ChevronRight :size="13"/></RouterLink></aside>
    </section>

    <section class="readiness-strip">
      <article v-for="market in ['moneyline','spread','total']" :key="market" :class="{ready:readiness.historical?.[market]}"><span>{{ marketLabel(market) }}</span><b>{{ readiness.historical?.[market] ? 'HISTORICAL READY' : 'SHADOW LOCKED' }}</b><small>{{ readiness.live?.[market]?.samples || 0 }} / 30 LIVE · BRIER {{ readiness.live?.[market]?.brier?.toFixed(3) || '—' }}</small></article>
    </section>

    <section class="controls">
      <div><small>MARKET</small><nav><button v-for="mode in ['moneyline','spread','total','mixed']" :key="mode" :class="{active:marketMode===mode}" @click="marketMode=mode">{{ mode === 'total' ? 'TOTALS' : mode.toUpperCase() }}</button></nav></div>
      <label><small>EVIDENCE</small><select v-model="evidenceMode"><option value="shadow">All shadow observations</option><option value="production">Automatic eligible only</option></select></label>
      <label><small>SLATE</small><select v-model="selectedWeek"><option v-for="week in availableWeeks" :key="week" :value="week">Week {{ week }}</option><option value="all">All upcoming weeks</option></select></label>
      <label><small>LEGS</small><select v-model.number="target"><option v-for="number in 9" :key="number" :value="number+1">{{ number+1 }}</option></select></label>
      <label><small>ODDS FLOOR</small><select v-model="minimumOdds"><option value="all">All listed odds</option><option v-for="floor in [1.2,1.3,1.4,1.5,1.75,2]" :key="floor" :value="floor">{{ floor }}+</option></select></label>
      <button class="refresh" :disabled="loading" @click="load"><RefreshCw :class="{spin:loading}"/> REFRESH</button>
    </section>

    <section class="workspace">
      <div class="inventory">
        <header><div><span class="eyebrow">CURRENT NFL BOARD</span><h2>{{ candidates.length }} decision-ready lines</h2></div><button :disabled="!candidates.length" @click="buildBest"><CircleGauge/> BUILD BEST {{ target }}</button></header>
        <div v-if="loading" class="state"><RefreshCw class="spin"/><b>Loading NFL distributions</b><p>Joining schedule, current prices, EPA history, calibrated models and immutable audit state.</p></div>
        <div v-else-if="error" class="state error"><AlertTriangle/><b>NFL board unavailable</b><p>{{ error }}</p></div>
        <div v-else-if="!candidates.length" class="state"><LockKeyhole/><b>No markets pass these controls</b><p>Automatic-only is expected to remain empty until 30 live observations pass the Brier gate. Switch to shadow observations to inspect and build research cards.</p></div>
        <div v-else class="candidate-list">
          <article v-for="row in candidates" :key="row.id">
            <div class="week"><b>W{{ weekNumber(row.game) }}</b><small>{{ row.game.date?.slice(5) }}</small></div>
            <div class="match"><small>{{ eventLabel(row.game) }} · {{ marketLabel(row.option.market) }}</small><b>{{ selectionLabel(row) }}</b><em>{{ scoreLabel(row.game) }}</em></div>
            <div class="evidence" :class="{ready:row.option.eligible}"><ShieldCheck v-if="row.option.eligible"/><LockKeyhole v-else/><span>{{ row.option.eligible ? 'AUTO ELIGIBLE' : row.option.market === 'moneyline' ? 'LIVE GATE PENDING' : 'HISTORICAL GATE FAILED' }}</span></div>
            <div class="price"><strong>{{ formatProbability(row.option.probability) }}</strong><small>{{ row.option.odds ? `@ ${row.option.odds.toFixed(3)}` : 'PRICE PENDING' }}</small></div>
            <button class="add" :disabled="(!selectedIds.has(row.id) && occupied.has(String(row.game.id))) || (!selectedIds.has(row.id) && selected.length >= target)" @click="toggle(row)"><Check v-if="selectedIds.has(row.id)"/><Plus v-else/></button>
          </article>
        </div>
      </div>

      <aside class="tray">
        <header><span><small>NFL CARD / {{ String(selected.length).padStart(2,'0') }}</small><b>{{ marketMode === 'mixed' ? 'Mixed markets' : marketLabel(marketMode) }}</b></span><button v-if="selected.length" @click="selected=[]"><Trash2/></button></header>
        <div v-if="!selected.length" class="tray-empty"><Layers3/><b>Build an NFL card</b><p>One selection per game. Locked markets remain clearly identified as research observations.</p></div>
        <div v-else class="legs"><article v-for="(row,index) in selected" :key="row.id"><span>{{ String(index+1).padStart(2,'0') }}</span><div><small>{{ marketLabel(row.option.market) }} · {{ formatProbability(row.option.probability) }}</small><b>{{ selectionLabel(row) }}</b><em>{{ eventLabel(row.game) }}</em></div><button @click="selected=selected.filter(item=>item.id!==row.id)">×</button></article></div>
        <footer><dl><div><dt>LEGS</dt><dd>{{ selected.length }}</dd></div><div><dt>JOINT MODEL</dt><dd>{{ selected.length ? formatProbability(jointProbability) : '—' }}</dd></div><div><dt>DECIMAL ODDS</dt><dd>{{ combinedOdds ? combinedOdds.toFixed(2) : '—' }}</dd></div><div><dt>MODE</dt><dd>{{ evidenceMode === 'production' ? 'AUTO' : 'SHADOW' }}</dd></div></dl><p><LockKeyhole/> Research cards do not trigger sportsbook autofill or place wagers.</p></footer>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.nfl-builder{--nfl:#ff754f;padding-bottom:64px}.hero{min-height:470px;display:grid;grid-template-columns:minmax(0,1fr) 390px;gap:64px;align-items:center;border-bottom:1px solid var(--line)}h1{margin:18px 0 25px;font-size:clamp(66px,8vw,116px);line-height:.82;letter-spacing:-.085em}h1 i{font-style:normal;color:var(--nfl)}.hero>div>p{max-width:770px;color:var(--muted);font-size:14px;line-height:1.7}.hero aside{min-height:320px;padding:28px;display:flex;flex-direction:column;background:var(--contrast);color:var(--on-contrast);border-top:5px solid var(--nfl)}.hero aside>svg{color:var(--nfl)}.hero aside>span{margin-top:auto;font:700 7px 'DM Mono';color:var(--nfl)}.hero aside b{margin:9px 0;font-size:28px;letter-spacing:-.05em}.hero aside p{color:#aeb4aa;font-size:9px;line-height:1.65}.hero aside a{width:max-content;display:flex;align-items:center;gap:7px;margin-top:12px;padding:9px 10px;border:1px solid #3d443b;color:var(--on-contrast);text-decoration:none;font:700 7px 'DM Mono'}.readiness-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:28px 0;background:var(--line);border:1px solid var(--line)}.readiness-strip article{min-height:93px;padding:15px;display:grid;gap:6px;background:var(--surface);border-top:3px solid #777}.readiness-strip article.ready{border-color:var(--nfl)}.readiness-strip span,.readiness-strip small{font:600 7px 'DM Mono';color:var(--muted)}.readiness-strip b{font:800 10px 'DM Mono'}.readiness-strip article.ready b{color:var(--nfl)}.controls{display:grid;grid-template-columns:minmax(340px,1fr) 190px 120px 82px 140px auto;gap:8px;align-items:end;margin-bottom:18px}.controls>div,.controls label{display:grid;gap:7px}.controls small{font:700 6px 'DM Mono';color:var(--muted)}.controls nav{height:46px;display:flex;border:1px solid var(--line)}.controls nav button{flex:1;border:0;border-right:1px solid var(--line);background:var(--surface);color:var(--text);font:700 7px 'DM Mono';cursor:pointer}.controls nav button.active{background:var(--contrast);color:var(--nfl)}.controls select,.refresh{height:46px;padding:0 11px;border:1px solid var(--line);background:var(--surface);color:var(--text);font:700 8px 'DM Mono'}.refresh{display:flex;align-items:center;gap:7px;cursor:pointer}.refresh svg{width:14px}.workspace{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(340px,.68fr);gap:18px}.inventory{border:1px solid var(--line);background:var(--surface)}.inventory>header{min-height:88px;padding:17px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line)}.inventory h2{margin:5px 0 0;font-size:24px}.inventory>header button{height:40px;padding:0 13px;display:flex;align-items:center;gap:7px;border:0;background:var(--contrast);color:var(--on-contrast);font:800 7px 'DM Mono';cursor:pointer}.inventory>header button svg{width:15px;color:var(--nfl)}.candidate-list>article{min-height:92px;padding:13px;display:grid;grid-template-columns:57px minmax(240px,1fr) 145px 95px 38px;align-items:center;gap:13px;border-bottom:1px solid var(--line)}.week{width:57px;height:57px;padding:8px;display:grid;place-items:center;background:color-mix(in srgb,var(--nfl) 12%,var(--surface));border:1px solid color-mix(in srgb,var(--nfl) 35%,var(--line))}.week b{font:800 8px 'DM Mono'}.week small,.match small,.match em,.price small{font:600 6px 'DM Mono';color:var(--muted)}.match{display:grid;gap:5px}.match b{font-size:14px}.match em{font-style:normal}.evidence{display:flex;align-items:center;gap:7px;color:var(--muted);font:700 6px 'DM Mono'}.evidence svg{width:14px}.evidence.ready{color:var(--nfl)}.price{display:grid;justify-items:end;gap:5px}.price strong{font:800 19px 'DM Mono'}.add{width:36px;height:36px;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface);color:var(--text);cursor:pointer}.add:disabled{opacity:.35}.state{min-height:350px;padding:40px;display:grid;place-items:center;align-content:center;text-align:center;gap:10px}.state svg{width:34px;height:34px;color:var(--nfl)}.state b{font-size:21px}.state p{max-width:550px;margin:0;color:var(--muted);font-size:9px;line-height:1.65}.tray{position:sticky;top:125px;align-self:start;background:var(--contrast);color:var(--on-contrast);border-top:5px solid var(--nfl)}.tray>header{height:77px;padding:15px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #343a33}.tray header span{display:grid;gap:5px}.tray header small{font:700 7px 'DM Mono';color:var(--nfl)}.tray header b{font-size:18px}.tray button{border:0;background:transparent;color:inherit;cursor:pointer}.tray-empty{min-height:300px;padding:30px;display:grid;place-items:center;align-content:center;text-align:center}.tray-empty svg{color:var(--nfl)}.tray-empty b{margin-top:16px}.tray-empty p{max-width:230px;color:#9ca49a;font-size:9px;line-height:1.6}.legs{max-height:470px;overflow:auto}.legs article{padding:13px;display:grid;grid-template-columns:23px 1fr 20px;gap:9px;border-bottom:1px solid #343a33}.legs article>span{font:700 7px 'DM Mono';color:var(--nfl)}.legs article div{display:grid;gap:4px}.legs small,.legs em{font:600 6px 'DM Mono';color:#9ca49a;font-style:normal}.legs b{font-size:10px}.tray footer{padding:15px;border-top:1px solid #343a33}.tray dl{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#343a33}.tray dl div{padding:10px;background:#151915}.tray dt{font:600 6px 'DM Mono';color:#929a90}.tray dd{margin:5px 0 0;font:800 15px 'DM Mono';color:var(--nfl)}.tray footer p{display:flex;justify-content:center;align-items:center;gap:6px;margin:13px 0 0;color:#929a90;font:600 6px 'DM Mono'}.tray footer svg{width:12px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:1100px){.controls{grid-template-columns:1fr 1fr 100px 150px}.controls>div{grid-column:1/-1}.workspace{grid-template-columns:1fr}.tray{position:static}}@media(max-width:800px){.hero{grid-template-columns:1fr;padding:45px 0}.hero aside{min-height:260px}.candidate-list>article{grid-template-columns:52px 1fr 80px 36px}.evidence{grid-column:2}.price{grid-column:3;grid-row:1/3}.add{grid-column:4;grid-row:1/3}}@media(max-width:620px){h1{font-size:57px}.readiness-strip{grid-template-columns:1fr}.controls{grid-template-columns:1fr 1fr}.controls label:nth-of-type(1){grid-column:1/-1}.refresh{width:100%}.workspace{margin:0 -13px}.candidate-list>article{grid-template-columns:47px 1fr 34px}.price{grid-column:2;grid-row:2;justify-items:start}.evidence{grid-column:2}.add{grid-column:3;grid-row:1/4}.inventory>header{align-items:flex-start;gap:10px}.inventory>header button{white-space:nowrap}}
</style>
