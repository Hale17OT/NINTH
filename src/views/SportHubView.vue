<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowRight, CheckCircle2, Database, LockKeyhole, Orbit, RefreshCw } from 'lucide-vue-next'
import { sportById } from '../config/sports'
import { esportsDisciplines } from '../config/sportWorkspaces'
import { api } from '../services/api'

const props = defineProps({ sport: { type: String, required: true }, section: { type: String, default: 'overview' } })
const route = useRoute()
const active = computed(() => sportById(props.sport))
const status = ref(null)
const statusError = ref('')
const statusLoading = ref(false)
const plans = computed(() => ({
  football: [
    ['Score engine', 'Time-decayed Dixon–Coles and bivariate Poisson score matrix'],
    ['Context layer', 'xG, xGA, shot quality, rest, travel, lineup strength and league priors'],
    ['Markets', '1X2, draw-no-bet, totals, both teams to score and exact-score distribution'],
  ],
  'american-football': [
    ['Drive engine', 'EPA/play, success rate, explosive rate and situation-neutral pace'],
    ['Personnel layer', 'Quarterback value, line continuity, injuries, rest and weather'],
    ['Markets', 'Moneyline, spread, total and team totals from joint score simulation'],
  ],
  basketball: [
    ['Possession engine', 'Pace-adjusted offensive and defensive efficiency distributions'],
    ['Lineup layer', 'RAPM-style player impact, availability, rest, travel and role stability'],
    ['Markets', 'Moneyline, spread, total and player props with minute uncertainty'],
  ],
  esports: [
    ['Series engine', 'Separate Valorant, CS2 and League of Legends ratings with chronological time decay'],
    ['Context layer', 'Roster continuity, map or side strength, patch context and conditional pick-ban trees'],
    ['Markets', 'Live shadow match winners now; map winners, handicaps and totals stay separately gated'],
  ],
}[active.value.id] || []))

const sourceRows = computed(() => status.value?.sources || [])
const modelState = computed(() => status.value?.modelState || (statusLoading.value ? 'CHECKING SOURCES' : 'STATUS UNAVAILABLE'))
const marketLabel = value => ({ home_win: 'Home win', over_2_5: 'Over 2.5', both_teams_score: 'Both teams to score', over_total: 'Game total', over_44_5: 'Over 44.5 points', over_228_5: 'Over 228.5 points' }[value] || String(value || '').replaceAll('_', ' '))
const percent = value => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
const decimal = value => value == null ? '—' : Number(value).toFixed(3)
const modelCards = computed(() => status.value?.models?.length
  ? status.value.models.map(report => {
      const hasWalkForward = Boolean(report.historical?.candidate?.samples)
      const audit = hasWalkForward ? report.historical.candidate : report.metrics || {}
      const ready = Boolean(report.historicalReadiness?.passed)
      return {
        id: `${report.sport}:${report.market}`, state: ready ? 'HISTORICAL READY / LIVE CHECK' : hasWalkForward ? 'THREE-YEAR WALK-FORWARD' : 'CHRONOLOGICAL HOLDOUT', title: `${({ valorant:'Valorant', cs2:'CS2', lol:'League of Legends' }[report.sport] || report.sport)} · ${marketLabel(report.market)}`,
        description: `${report.method?.replaceAll('_', ' ')} · audited through ${(hasWalkForward ? report.historical?.end : report.timeRange?.training_through)?.slice(0, 10) || '—'}`,
        brier: decimal(audit.brier), calibration: percent(audit.expected_calibration_error),
        samples: hasWalkForward ? report.historical.samples : report.samples?.untouched_test || 0, sampleLabel: hasWalkForward ? 'WALK-FORWARD N' : 'HOLDOUT N', accuracy: percent(audit.accuracy),
        passed: ready, oddsIndependent: report.oddsIndependent === true,
      }
    })
  : plans.value.map(plan => ({ id: plan[0], state: modelState.value, title: plan[0], description: plan[1], brier: '—', calibration: '—', samples: 0, accuracy: '—', passed: false })))
const loadStatus = async () => {
  statusLoading.value = true
  statusError.value = ''
  try { status.value = await api.sportDirectory(props.sport, 'status') }
  catch (error) { statusError.value = error?.message || 'Source status could not be loaded.' }
  finally { statusLoading.value = false }
}
watch(() => props.sport, loadStatus)
onMounted(loadStatus)
</script>

<template>
  <div class="sport-hub" :style="{ '--sport': active.accent }">
    <section class="sport-hero">
      <div><span class="eyebrow">{{ active.eyebrow }} / NINTH RESEARCH LAB</span><h1>{{ active.name }}<br><i>intelligence.</i></h1><p>{{ active.description }}</p><div class="lab-state"><i></i> {{ active.id === 'esports' ? 'LIVE DATA · SHADOW MODELS' : 'SHADOW FOUNDATION · NOT YET PRODUCTION ELIGIBLE' }}</div></div>
      <aside><Orbit :size="36"/><span>MODEL STATE</span><b>Evidence before exposure.</b><p>No selection enters the all-sports builder until it beats its sport-specific baseline on untouched chronological data and survives live forward testing.</p></aside>
    </section>

    <template v-if="section === 'overview'">
      <section class="league-strip"><span v-for="league in active.leagues" :key="league">{{ league }}</span></section>
      <section v-if="active.id === 'esports'" class="discipline-grid">
        <article v-for="discipline in esportsDisciplines" :key="discipline.id" :style="{'--discipline':discipline.accent}">
          <header><b>{{ discipline.code }}</b><span>{{ discipline.leagues }}</span></header>
          <h2>{{ discipline.name }}</h2><p>{{ discipline.engine }}</p>
          <footer><span>{{ discipline.source }}</span><em>SEPARATE MODEL LEDGER</em></footer>
        </article>
      </section>
      <section class="architecture"><header><span class="eyebrow">SPORT-NATIVE ARCHITECTURE</span><h2>Built around how {{ active.name.toLowerCase() }} is actually played.</h2></header><div><article v-for="(plan,index) in plans" :key="plan[0]"><small>0{{ index + 1 }}</small><Activity/><h3>{{ plan[0] }}</h3><p>{{ plan[1] }}</p></article></div></section>
      <section class="release-gate"><div><LockKeyhole/><span><small>PRODUCTION CONTRACT</small><b>Locked before it is trusted.</b></span></div><ul><li><CheckCircle2/> Expanding-window, season-separated validation</li><li><CheckCircle2/> Brier, log loss, calibration error and Wilson bounds</li><li><CheckCircle2/> Immutable pre-event prediction ledger and live shadow period</li></ul></section>
    </template>

    <section v-else-if="section === 'models'" class="lab-page">
      <header><span class="eyebrow">MODEL LAB / LIVE REGISTRY</span><h2>Candidate families and promotion gates.</h2><p>This page reports the actual source and release state. It never invents accuracy metrics before a chronological prediction ledger exists.</p><button class="status-refresh" :disabled="statusLoading" @click="loadStatus"><RefreshCw :class="{spin:statusLoading}"/> REFRESH STATUS</button></header>
      <div v-if="statusError" class="status-error">{{ statusError }}</div>
      <div class="model-cards"><article v-for="model in modelCards" :key="model.id"><span>{{ model.state }}</span><h3>{{ model.title }}</h3><p>{{ model.description }}</p><dl><div><dt>OOS BRIER</dt><dd>{{ model.brier }}</dd></div><div><dt>CALIBRATION</dt><dd>{{ model.calibration }}</dd></div><div><dt>{{ model.sampleLabel || 'AUDIT N' }}</dt><dd>{{ model.samples }}</dd></div></dl><footer><span>OOS ACCURACY {{ model.accuracy }}<template v-if="model.oddsIndependent"> · NO ODDS</template></span><em>{{ model.passed ? 'LIVE PIPELINE CHECK' : 'SHADOW LOCKED' }}</em></footer></article></div>
    </section>

    <section v-else class="lab-page sources-page">
      <header><span class="eyebrow">DATA LINEAGE / LIVE STATUS</span><h2>Every input needs a source and an availability time.</h2><p>Event-time and knowledge-time are stored separately so late injury, lineup or veto information cannot leak backward into training.</p><button class="status-refresh" :disabled="statusLoading" @click="loadStatus"><RefreshCw :class="{spin:statusLoading}"/> REFRESH STATUS</button></header>
      <div v-if="statusError" class="status-error">{{ statusError }}</div>
      <div class="source-table"><article v-for="row in sourceRows" :key="row.id"><Database/><span><small>{{ row.name }} / {{ row.env }}</small><b>{{ row.role }}</b><p>{{ row.detail }}</p></span><em :class="row.state">{{ row.state }}</em></article><div v-if="statusLoading && !sourceRows.length" class="source-loading"><RefreshCw class="spin"/> CHECKING CONFIGURATION</div></div>
    </section>

    <footer class="research-footer"><span>{{ route.path.toUpperCase() }}</span><RouterLink to="/build">ALL-SPORTS BUILDER <ArrowRight :size="14"/></RouterLink></footer>
  </div>
</template>

<style scoped>
.sport-hub{--accent:var(--sport);display:grid}.sport-hero{min-height:510px;display:grid;grid-template-columns:1fr 390px;gap:55px;align-items:center;border-bottom:1px solid var(--line)}h1{margin:18px 0 25px;font-size:clamp(65px,8.6vw,125px);line-height:.8;letter-spacing:-.09em}h1 i{font-style:normal;color:var(--sport)}.sport-hero>div>p{max-width:680px;color:var(--muted);font-size:15px;line-height:1.65}.lab-state{display:inline-flex;align-items:center;gap:8px;margin-top:25px;padding:10px 12px;border:1px solid var(--line);font:700 7px 'DM Mono';letter-spacing:.07em}.lab-state i{width:7px;height:7px;background:var(--sport);border-radius:50%}.sport-hero aside{min-height:330px;padding:30px;display:flex;flex-direction:column;background:var(--contrast);color:var(--on-contrast);border-top:5px solid var(--sport)}.sport-hero aside svg{color:var(--sport)}.sport-hero aside span{margin-top:auto;font:700 7px 'DM Mono';color:var(--sport)}.sport-hero aside b{margin:10px 0;font-size:30px;letter-spacing:-.05em}.sport-hero aside p{font-size:10px;line-height:1.7;color:#aeb4aa}.league-strip{display:flex;gap:1px;background:var(--line);border-bottom:1px solid var(--line)}.league-strip span{flex:1;padding:18px;background:var(--paper);text-align:center;font:700 8px 'DM Mono';white-space:nowrap}.discipline-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;margin-top:42px;background:var(--line);border:1px solid var(--line)}.discipline-grid article{min-height:290px;padding:26px;display:flex;flex-direction:column;background:linear-gradient(145deg,color-mix(in srgb,var(--discipline) 13%,var(--surface)),var(--surface) 55%);border-top:5px solid var(--discipline)}.discipline-grid header,.discipline-grid footer{display:flex;align-items:center;justify-content:space-between}.discipline-grid header b{font:800 28px 'DM Mono';color:var(--discipline)}.discipline-grid header span,.discipline-grid footer{font:600 7px 'DM Mono';color:var(--muted)}.discipline-grid h2{margin:auto 0 10px;font-size:42px;letter-spacing:-.06em}.discipline-grid p{max-width:500px;font-size:10px;line-height:1.7;color:var(--muted)}.discipline-grid footer{padding-top:15px;border-top:1px solid var(--line)}.discipline-grid footer em{font-style:normal;color:var(--discipline)}.architecture,.lab-page{padding:52px 0}.architecture>header,.lab-page>header{max-width:780px}.architecture h2,.lab-page h2{margin:9px 0;font-size:38px;letter-spacing:-.06em}.architecture>div,.model-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin-top:25px;background:var(--line);border:1px solid var(--line)}.architecture article,.model-cards article{min-height:245px;padding:24px;background:var(--surface);display:flex;flex-direction:column}.architecture article small{font:700 9px 'DM Mono';color:var(--sport)}.architecture article svg{margin:30px 0 15px;color:var(--sport)}.architecture h3,.model-cards h3{font-size:19px;margin:0}.architecture p,.model-cards p,.lab-page header p{font-size:10px;line-height:1.7;color:var(--muted)}.release-gate{display:grid;grid-template-columns:1fr 1.2fr;gap:1px;margin-bottom:50px;background:var(--line);border:1px solid var(--line)}.release-gate>div,.release-gate ul{margin:0;padding:27px;background:var(--contrast);color:var(--on-contrast)}.release-gate>div{display:flex;align-items:center;gap:14px}.release-gate svg{color:var(--sport)}.release-gate span{display:grid;gap:5px}.release-gate small{font:700 7px 'DM Mono';color:var(--sport)}.release-gate b{font-size:18px}.release-gate ul{display:grid;gap:12px;list-style:none}.release-gate li{display:flex;align-items:center;gap:9px;font-size:9px}.model-cards article>span{align-self:flex-start;padding:5px 7px;background:color-mix(in srgb,var(--sport) 16%,transparent);color:var(--sport);font:700 7px 'DM Mono'}.model-cards h3{margin-top:35px}.model-cards dl{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:auto 0 0;background:var(--line)}.model-cards dl div{padding:9px;background:var(--surface)}.model-cards dt{font:600 6px 'DM Mono';color:var(--muted)}.model-cards dd{margin:6px 0 0;font:700 13px 'DM Mono'}.model-cards article>footer{display:flex;justify-content:space-between;gap:10px;margin-top:13px;padding-top:11px;border-top:1px solid var(--line);font:700 6px 'DM Mono';color:var(--muted)}.model-cards article>footer em{font-style:normal;color:var(--sport)}.source-table{margin-top:26px;border:1px solid var(--line)}.source-table article{display:grid;grid-template-columns:26px 1fr auto;align-items:center;gap:14px;padding:17px;border-bottom:1px solid var(--line)}.source-table article:last-child{border:0}.source-table svg{color:var(--sport)}.source-table span{display:grid;gap:4px}.source-table small{font:600 7px 'DM Mono';color:var(--muted)}.source-table b{font-size:12px}.source-table p{margin:2px 0 0;color:var(--muted);font-size:9px}.source-table em{padding:6px 8px;font:700 7px 'DM Mono';font-style:normal;text-transform:uppercase;color:var(--muted);border:1px solid var(--line)}.source-table em.ready,.source-table em.available{color:var(--sport)}.source-table em.required{color:#ff754f}.status-refresh{display:flex;align-items:center;gap:8px;margin-top:18px;padding:10px 12px;border:1px solid var(--line);background:var(--surface);color:var(--text);font:700 7px 'DM Mono';cursor:pointer}.status-refresh svg{width:13px}.status-refresh:disabled{opacity:.55}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.status-error{margin-top:18px;padding:13px;border:1px solid #ff754f;color:#ff754f;font:700 8px 'DM Mono'}.source-loading{min-height:150px;display:flex;align-items:center;justify-content:center;gap:10px;font:700 8px 'DM Mono'}.source-loading svg{width:16px;color:var(--sport)}.research-footer{display:flex;justify-content:space-between;padding:18px 0;border-top:1px solid var(--line);font:700 7px 'DM Mono';color:var(--muted)}.research-footer a{display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--text)}@media(max-width:900px){.sport-hero{grid-template-columns:1fr;padding:42px 0}.architecture>div,.model-cards{grid-template-columns:1fr}.release-gate{grid-template-columns:1fr}.league-strip{overflow-x:auto}.league-strip span{min-width:150px}}@media(max-width:700px){.discipline-grid{grid-template-columns:1fr}.discipline-grid article{min-height:240px}}@media(max-width:600px){h1{font-size:55px}.sport-hero aside{min-height:250px}.source-table article{grid-template-columns:25px 1fr}.source-table em{grid-column:2}.model-cards dl{grid-template-columns:1fr}}
.discipline-grid{grid-template-columns:repeat(3,1fr)}
@media(max-width:1050px){.discipline-grid{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.discipline-grid{grid-template-columns:1fr}}
</style>
