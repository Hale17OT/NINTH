<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, Check, ChevronRight, Layers3, LockKeyhole, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { api } from '../services/api'
import { sports } from '../config/sports'

const loading = ref(true)
const error = ref('')
const board = ref(null)
const researchBoards = ref({ football: [], 'american-football': [], basketball: [], esports: [] })
const activeSport = ref('all')
const viewMode = ref('production')
const selected = ref([])
const today = () => {
  const date = new Date(), offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 10)
}
const sportState = sport => sport.id === 'baseball' ? 'LIVE BOARD' : researchBoards.value[sport.id]?.some(game => game.prediction) ? 'SHADOW BOARD' : 'RESEARCH LOCKED'
const productionCandidates = computed(() => (board.value?.games || []).flatMap(game => {
  const rows = []
  if (game.automatic_moneyline_eligible && game.recommended_side && game.recommended_probability) {
    const side = game.recommended_side
    const team = game[side]
    rows.push({
      id: `mlb:${game.game_id}:moneyline:${side}`, sport: 'baseball', sportLabel: 'MLB', gameId: game.game_id,
      event: `${game.away.name} @ ${game.home.name}`, startsAt: game.starts_at,
      market: 'Moneyline', selection: `${team.name} to win`, probability: game.recommended_probability,
      odds: Number(game.moneyline_odds?.[side] || 0), evidence: 'PRODUCTION ELIGIBLE',
    })
  }
  const total = game.totals_projection
  if (total?.automatic_builder_eligible && total.recommended_line && total.recommended_side) {
    const threshold = (total.thresholds || []).find(row => Number(row.line) === Number(total.recommended_line))
    rows.push({
      id: `mlb:${game.game_id}:total:${total.recommended_side}:${total.recommended_line}`, sport: 'baseball', sportLabel: 'MLB', gameId: game.game_id,
      event: `${game.away.name} @ ${game.home.name}`, startsAt: game.starts_at, market: 'Total runs',
      selection: `${total.recommended_side.toUpperCase()} ${total.recommended_line}`,
      probability: total.recommended_probability, odds: Number(threshold?.melbet_odds?.[total.recommended_side] || 0), evidence: 'PRODUCTION ELIGIBLE',
    })
  }
  return rows
}).sort((a,b) => b.probability - a.probability))
const researchCandidates = computed(() => Object.entries(researchBoards.value).flatMap(([sport, games]) => games.flatMap(game => {
  const prediction = game.prediction
  if (!prediction?.markets) return []
  if (sport === 'football') {
    const choices = [['home_win', game.home?.name, '1'], ['draw', 'Draw', 'X'], ['away_win', game.away?.name, '2']]
      .map(([key, name, code]) => ({ key, name, code, probability: Number(prediction.markets[key] || 0) }))
    const strongest = choices.sort((a,b) => b.probability - a.probability)[0]
    return [{ id: `${sport}:${game.id}:1x2:${strongest.key}`, sport, sportLabel: 'FTB', gameId: game.id,
      event: `${game.away?.name} @ ${game.home?.name}`, startsAt: game.timestamp || `${game.date}T${game.time}`,
      market: '1X2', selection: `${strongest.code} · ${strongest.name}`, probability: strongest.probability, odds: 0,
      evidence: 'SHADOW ONLY · NOT WAGER ELIGIBLE' }]
  }
  if (sport === 'american-football') {
    const home = Number(prediction.markets.home_win || 0), away = Number(prediction.markets.away_win || 0), useHome = home >= away
    return [{ id: `${sport}:${game.id}:moneyline:${useHome?'home':'away'}`, sport, sportLabel: 'NFL', gameId: game.id,
      event: `${game.away?.name} @ ${game.home?.name}`, startsAt: game.timestamp || `${game.date}T${game.time}`,
      market: 'Moneyline', selection: `${useHome ? game.home?.name : game.away?.name} to win`, probability: useHome ? home : away, odds: 0,
      evidence: 'SHADOW ONLY · NOT WAGER ELIGIBLE' }]
  }
  if (sport === 'esports') {
    const home = Number(prediction.markets.home_win || 0), away = Number(prediction.markets.away_win || 0), useHome = home >= away
    return [{ id: `${sport}:${game.id}:match-winner:${useHome?'home':'away'}`, sport, sportLabel: game.competitionCode || 'ESP', gameId: game.id,
      event: `${game.away?.name} vs ${game.home?.name}`, startsAt: game.timestamp || `${game.date}T${game.time}`,
      market: 'Match winner', selection: `${useHome ? game.home?.name : game.away?.name} to win`, probability: useHome ? home : away, odds: 0,
      evidence: `${prediction.modelStatus || 'LIVE SHADOW'} · NOT WAGER ELIGIBLE` }]
  }
  return []
})).sort((a,b) => b.probability - a.probability))
const candidates = computed(() => viewMode.value === 'production' ? productionCandidates.value : [...productionCandidates.value, ...researchCandidates.value].sort((a,b) => b.probability - a.probability))
const visible = computed(() => activeSport.value === 'all' ? candidates.value : candidates.value.filter(row => row.sport === activeSport.value))
const selectedIds = computed(() => new Set(selected.value.map(row => row.id)))
const occupiedEvents = computed(() => new Set(selected.value.map(row => `${row.sport}:${row.gameId}`)))
const jointProbability = computed(() => selected.value.reduce((product,row) => product * row.probability, 1))
const combinedOdds = computed(() => selected.value.length && selected.value.every(row => row.odds > 0) ? selected.value.reduce((product,row) => product * row.odds, 1) : null)
const eventCount = computed(() => new Set(selected.value.map(row => `${row.sport}:${row.gameId}`)).size)
const add = row => {
  if (!selectedIds.value.has(row.id) && !occupiedEvents.value.has(`${row.sport}:${row.gameId}`)) selected.value.push(row)
}
const addBest = () => {
  if (viewMode.value === 'production') { selected.value = candidates.value.slice(0, 5); return }
  const picked = [], seen = new Set()
  for (const sport of ['baseball', 'football', 'american-football', 'basketball', 'esports']) {
    const row = candidates.value.find(item => item.sport === sport)
    if (row) { picked.push(row); seen.add(row.id) }
  }
  for (const row of candidates.value) {
    if (picked.length >= 5) break
    if (!seen.has(row.id)) { picked.push(row); seen.add(row.id) }
  }
  selected.value = picked
}
const setMode = mode => { viewMode.value = mode; selected.value = []; activeSport.value = 'all' }
const formatProbability = value => `${(Number(value || 0) * 100).toFixed(1)}%`
const load = async () => {
  loading.value = true; error.value = ''
  try {
    const [production, football, nfl, basketball, esports] = await Promise.all([
      api.projectionBoard(today(), 1), api.sportDirectory('football', 'games'),
      api.sportDirectory('american-football', 'games'), api.sportDirectory('basketball', 'games'),
      api.sportDirectory('esports', 'games'),
    ])
    board.value = production
    researchBoards.value = { football: football.items || [], 'american-football': nfl.items || [], basketball: basketball.items || [], esports: esports.items || [] }
  }
  catch (caught) { error.value = caught?.message || 'The production board could not be loaded.' }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="universal-builder">
    <section class="builder-hero">
      <div><span class="eyebrow">NINTH / ALL-SPORTS BUILDER</span><h1>One card.<br><i>Every arena.</i></h1><p>A shared construction surface with separate model eligibility. Baseball can contribute production legs now; every other sport unlocks automatically only after its own evidence gate passes.</p></div>
      <aside><Layers3/><span>PORTFOLIO CONTRACT</span><b>Combined does not mean blended.</b><p>Probabilities come from sport-native models. The builder only joins eligible outputs and then controls event, team, market and directional exposure across the final card.</p></aside>
    </section>

    <section class="sport-lanes">
      <button :class="{active:activeSport==='all'}" @click="activeSport='all'"><small>00</small><b>ALL</b><span>{{ candidates.length }} READY</span></button>
      <button v-for="sport in sports" :key="sport.id" :class="{active:activeSport===sport.id}" :style="{'--lane':sport.accent}" @click="activeSport=sport.id"><small>{{ sport.numeral }}</small><b>{{ sport.short }}</b><span>{{ sportState(sport) }}</span></button>
    </section>

    <section class="mode-switch" aria-label="Builder evidence mode"><button :class="{active:viewMode==='production'}" @click="setMode('production')"><b>PRODUCTION</b><span>Only audited, automatically eligible legs</span></button><button :class="{active:viewMode==='shadow'}" @click="setMode('shadow')"><b>RESEARCH SHADOW</b><span>Preview locked Football, NFL and Esports forecasts</span></button></section>

    <section class="builder-grid">
      <div class="inventory">
        <header><div><span class="eyebrow">{{ viewMode === 'production' ? 'ELIGIBLE INVENTORY' : 'RESEARCH INVENTORY' }}</span><h2>{{ viewMode === 'production' ? 'Today’s audited legs' : 'Current shadow forecasts' }}</h2></div><div><button @click="load"><RefreshCw :size="14"/> REFRESH</button><button class="best" :disabled="!candidates.length" @click="addBest">{{ viewMode === 'production' ? 'ADD BEST 5' : 'ADD CROSS-SPORT 5' }}</button></div></header>
        <div v-if="loading" class="state"><RefreshCw class="spin"/><b>Syncing sport adapters</b><span>Reading immutable production boards.</span></div>
        <div v-else-if="error" class="state error"><AlertTriangle/><b>Board unavailable</b><span>{{ error }}</span></div>
        <div v-else-if="viewMode === 'production' && activeSport !== 'all' && activeSport !== 'baseball'" class="state locked"><LockKeyhole/><b>{{ sports.find(s=>s.id===activeSport)?.name }} is evidence-locked</b><span>Switch to Research shadow to inspect forecasts without making them wager-eligible.</span><RouterLink :to="sports.find(s=>s.id===activeSport)?.route + '/models'">VIEW MODEL LAB <ChevronRight :size="13"/></RouterLink></div>
        <div v-else class="candidate-list">
          <article v-for="row in visible" :key="row.id">
            <div class="sport-code">{{ row.sportLabel }}</div><div class="candidate-main"><small>{{ row.event }} · {{ row.market }}</small><b>{{ row.selection }}</b><span>{{ row.evidence }}</span></div><div class="price"><strong>{{ formatProbability(row.probability) }}</strong><small>{{ row.odds ? `@ ${row.odds.toFixed(3)}` : 'PRICE PENDING' }}</small></div><button :disabled="selectedIds.has(row.id) || occupiedEvents.has(`${row.sport}:${row.gameId}`)" :title="occupiedEvents.has(`${row.sport}:${row.gameId}`) ? 'One leg per event' : 'Add leg'" @click="add(row)"><Check v-if="selectedIds.has(row.id) || occupiedEvents.has(`${row.sport}:${row.gameId}`)"/><Plus v-else/></button>
          </article>
          <div v-if="!visible.length" class="state"><AlertTriangle/><b>No eligible legs in this lane</b><span>The builder does not substitute manual-only forecasts.</span></div>
        </div>
      </div>

      <aside class="card-tray">
        <header><span><small>CARD / {{ String(selected.length).padStart(2,'0') }}</small><b>Combined build</b></span><button v-if="selected.length" @click="selected=[]"><Trash2 :size="14"/></button></header>
        <div v-if="!selected.length" class="tray-empty"><Layers3/><b>Add an audited leg</b><p>Eligible markets from every unlocked sport will share this tray.</p></div>
        <div v-else class="tray-legs"><article v-for="(row,index) in selected" :key="row.id"><span>{{ String(index+1).padStart(2,'0') }}</span><div><small>{{ row.sportLabel }} · {{ row.market }}</small><b>{{ row.selection }}</b><em>{{ row.event }}</em></div><button @click="selected=selected.filter(item=>item.id!==row.id)">×</button></article></div>
        <footer><dl><div><dt>LEGS</dt><dd>{{ selected.length }}</dd></div><div><dt>EVENTS</dt><dd>{{ eventCount }}</dd></div><div><dt>JOINT MODEL</dt><dd>{{ selected.length ? formatProbability(jointProbability) : '—' }}</dd></div><div><dt>DECIMAL ODDS</dt><dd>{{ combinedOdds ? combinedOdds.toFixed(2) : '—' }}</dd></div></dl><p>No wager is placed from this research surface.</p></footer>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.universal-builder{padding-bottom:60px}.builder-hero{min-height:500px;display:grid;grid-template-columns:1fr 390px;gap:65px;align-items:center;border-bottom:1px solid var(--line)}h1{margin:18px 0 26px;font-size:clamp(68px,8.5vw,124px);line-height:.8;letter-spacing:-.09em}h1 i{font-style:normal;color:var(--accent)}.builder-hero>div>p{max-width:750px;color:var(--muted);font-size:15px;line-height:1.7}.builder-hero aside{min-height:335px;padding:30px;display:flex;flex-direction:column;background:var(--contrast);color:var(--on-contrast);border-top:5px solid var(--accent)}.builder-hero aside svg{color:var(--accent)}.builder-hero aside span{margin-top:auto;font:700 7px 'DM Mono';color:var(--accent)}.builder-hero aside b{margin:10px 0;font-size:29px;letter-spacing:-.05em}.builder-hero aside p{color:#aeb4aa;font-size:10px;line-height:1.7}.sport-lanes{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;margin:34px 0;background:var(--line);border:1px solid var(--line)}.sport-lanes button{height:105px;padding:14px;display:grid;align-content:space-between;text-align:left;border:0;background:var(--surface);color:var(--text);cursor:pointer;border-top:4px solid transparent}.sport-lanes button:hover,.sport-lanes button.active{background:color-mix(in srgb,var(--lane,var(--accent)) 11%,var(--surface));border-color:var(--lane,var(--accent))}.sport-lanes small{font:500 7px 'DM Mono';color:var(--muted)}.sport-lanes b{font:800 18px 'DM Mono'}.sport-lanes span{font:600 6px 'DM Mono';color:var(--muted)}.builder-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(350px,.7fr);gap:18px}.inventory,.card-tray{border:1px solid var(--line);background:var(--surface)}.inventory>header{min-height:90px;padding:18px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.inventory h2{margin:5px 0 0;font-size:25px;letter-spacing:-.05em}.inventory>header>div:last-child{display:flex;gap:7px}.inventory>header button{height:36px;padding:0 11px;display:flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--surface);font:700 7px 'DM Mono';cursor:pointer}.inventory>header .best{background:var(--contrast);color:var(--on-contrast)}.candidate-list article{min-height:82px;padding:13px;display:grid;grid-template-columns:47px 1fr auto 38px;align-items:center;gap:13px;border-bottom:1px solid var(--line)}.sport-code{width:47px;height:47px;display:grid;place-items:center;background:var(--contrast);color:var(--accent);font:800 8px 'DM Mono'}.candidate-main{display:grid;gap:5px}.candidate-main small{font:600 7px 'DM Mono';color:var(--muted)}.candidate-main b{font-size:13px}.candidate-main span{font:700 6px 'DM Mono';color:var(--acid)}.price{display:grid;justify-items:end;gap:4px}.price strong{font:800 19px 'DM Mono'}.price small{font:600 6px 'DM Mono';color:var(--muted)}.candidate-list article>button{width:36px;height:36px;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface);cursor:pointer}.candidate-list article>button:disabled{color:var(--acid);background:var(--wash)}.state{min-height:330px;padding:40px;display:grid;place-items:center;align-content:center;text-align:center;gap:10px}.state svg{color:var(--accent)}.state b{font-size:20px}.state span{max-width:540px;color:var(--muted);font-size:9px;line-height:1.65}.state a{display:flex;gap:7px;align-items:center;margin-top:10px;padding:10px;background:var(--contrast);color:var(--on-contrast);text-decoration:none;font:700 7px 'DM Mono'}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.card-tray{position:sticky;top:130px;align-self:start;background:var(--contrast);color:var(--on-contrast)}.card-tray>header{height:80px;padding:17px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #333a32}.card-tray header span{display:grid;gap:5px}.card-tray header small{font:600 7px 'DM Mono';color:var(--accent)}.card-tray header b{font-size:19px}.card-tray header button,.tray-legs button{border:0;background:transparent;color:var(--on-contrast);cursor:pointer}.tray-empty{min-height:330px;padding:30px;display:grid;place-items:center;align-content:center;text-align:center}.tray-empty svg{color:var(--accent)}.tray-empty b{margin-top:18px}.tray-empty p{max-width:220px;color:#98a095;font-size:9px;line-height:1.6}.tray-legs{max-height:470px;overflow:auto}.tray-legs article{padding:13px;display:grid;grid-template-columns:24px 1fr 20px;gap:9px;border-bottom:1px solid #333a32}.tray-legs article>span{font:700 7px 'DM Mono';color:var(--accent)}.tray-legs article>div{display:grid;gap:4px}.tray-legs small,.tray-legs em{font:600 6px 'DM Mono';color:#9ca49a;font-style:normal}.tray-legs b{font-size:10px}.card-tray footer{padding:16px;border-top:1px solid #333a32}.card-tray dl{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#333a32}.card-tray dl div{padding:11px;background:#151915}.card-tray dt{font:600 6px 'DM Mono';color:#929a90}.card-tray dd{margin:5px 0 0;font:800 16px 'DM Mono';color:var(--accent)}.card-tray footer p{margin:13px 0 0;font:600 6px 'DM Mono';color:#929a90;text-align:center}@media(max-width:1050px){.builder-grid{grid-template-columns:1fr}.card-tray{position:static}.sport-lanes{grid-template-columns:repeat(3,1fr)}}@media(max-width:800px){.builder-hero{grid-template-columns:1fr;padding:45px 0}.builder-hero aside{min-height:270px}}@media(max-width:600px){h1{font-size:58px}.sport-lanes{grid-template-columns:repeat(2,1fr)}.inventory>header{align-items:flex-start;gap:12px}.inventory>header>div:last-child{display:grid}.candidate-list article{grid-template-columns:42px 1fr 34px}.candidate-list .price{grid-column:2;grid-row:2;justify-items:start}.candidate-list article>button{grid-column:3;grid-row:1/3}.builder-grid{margin:0 -13px}.card-tray{border-left:0;border-right:0}}
.mode-switch{display:grid;grid-template-columns:1fr 1fr;gap:1px;margin:-18px 0 34px;background:var(--line);border:1px solid var(--line)}.mode-switch button{min-height:62px;padding:13px 16px;display:grid;gap:5px;text-align:left;border:0;border-left:4px solid transparent;background:var(--surface);color:var(--text);cursor:pointer}.mode-switch button.active{border-left-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,var(--surface))}.mode-switch b{font:800 9px 'DM Mono'}.mode-switch span{font:600 7px 'DM Mono';color:var(--muted)}@media(max-width:600px){.mode-switch{grid-template-columns:1fr}}
</style>
