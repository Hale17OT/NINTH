<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowRight, CheckCircle2, Database, LockKeyhole, Orbit, RefreshCw } from 'lucide-vue-next'
import { motion } from 'motion-v'
import { sportById } from '../config/sports'
import { esportsDisciplines } from '../config/sportWorkspaces'
import { api } from '../services/api'
import SportVisual from '../components/ui/SportVisual.vue'
import EvidenceBadge from '../components/ui/EvidenceBadge.vue'
import BorderTrail from '../components/motion/BorderTrail.vue'

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
    ['Markets', 'Current match-winner probabilities; map winners, handicaps and totals remain separately evidence-gated'],
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
        id: `${report.sport}:${report.modelFamily||report.modelName||''}:${report.market}`, state: report.decision ? `${report.decision} · TWO-SEASON HOLDOUT` : ready ? 'HISTORICAL READY / LIVE CHECK' : hasWalkForward ? 'THREE-YEAR WALK-FORWARD' : 'CHRONOLOGICAL HOLDOUT', title: `${report.modelName || ({ valorant:'Valorant', cs2:'CS2', lol:'League of Legends' }[report.sport] || report.sport)} · ${marketLabel(report.market)}`,
        description: `${report.method?.replaceAll('_', ' ')} · development data through ${(hasWalkForward ? report.historical?.end : report.timeRange?.trainingThrough || report.timeRange?.training_through)?.slice(0, 10) || '—'}`,
        brier: decimal(audit.brier), calibration: percent(audit.expected_calibration_error),
        samples: hasWalkForward ? report.historical.samples : report.samples?.untouched_test || 0, sampleLabel: hasWalkForward ? 'WALK-FORWARD N' : 'HOLDOUT N', accuracy: percent(audit.accuracy),
        passed: ready, decision:report.decision, oddsIndependent: report.oddsIndependent === true,
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
      <div class="sport-beam" aria-hidden="true"></div>
      <div class="sport-copy"><EvidenceBadge state="brand">{{ active.eyebrow }} / NINTH MODEL LAB</EvidenceBadge><h1>{{ active.name }}<br><i>intelligence.</i></h1><p>{{ active.description }}</p><div class="lab-state"><i></i> {{ active.id === 'esports' ? 'LIVE DATA · MODEL PROBABILITIES' : 'HISTORICAL EVIDENCE · BUILDER GATES APPLY' }}</div></div>
      <motion.div class="sport-object" :initial="{opacity:0,scale:.86,rotate:-8}" :animate="{opacity:1,scale:1,rotate:0}" :transition="{type:'spring',stiffness:120,damping:19}"><SportVisual :sport="active.id" :accent="active.accent" compact/></motion.div>
      <aside><BorderTrail/><Orbit :size="36"/><span>MODEL STATE</span><b>Evidence before exposure.</b><p>No selection enters the all-sports builder until it beats its sport-specific baseline on untouched chronological data and survives live forward testing.</p></aside>
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
      <section class="release-gate"><div><LockKeyhole/><span><small>EVIDENCE CONTRACT</small><b>Locked before it is trusted.</b></span></div><ul><li><CheckCircle2/> Expanding-window, season-separated validation</li><li><CheckCircle2/> Brier, log loss, calibration error and Wilson bounds</li><li><CheckCircle2/> Immutable pre-event prediction ledger and recent forward record</li></ul></section>
    </template>

    <section v-else-if="section === 'models'" class="lab-page">
      <header><span class="eyebrow">MODEL LAB / PERFORMANCE</span><h2>Model families and evidence gates.</h2><p>This page reports the actual source and evaluation state. It never invents accuracy metrics before a chronological prediction ledger exists.</p><button class="status-refresh" :disabled="statusLoading" @click="loadStatus"><RefreshCw :class="{spin:statusLoading}"/> REFRESH STATUS</button></header>
      <div v-if="statusError" class="status-error">{{ statusError }}</div>
      <div class="model-cards"><article v-for="model in modelCards" :key="model.id"><span>{{ model.state }}</span><h3>{{ model.title }}</h3><p>{{ model.description }}</p><dl><div><dt>OOS BRIER</dt><dd>{{ model.brier }}</dd></div><div><dt>CALIBRATION</dt><dd>{{ model.calibration }}</dd></div><div><dt>{{ model.sampleLabel || 'AUDIT N' }}</dt><dd>{{ model.samples }}</dd></div></dl><footer><span>OOS ACCURACY {{ model.accuracy }}<template v-if="model.oddsIndependent"> · ODDS EXCLUDED FROM FEATURES</template></span><em>{{ model.decision || (model.passed ? 'HISTORICAL EVIDENCE' : 'MORE EVIDENCE REQUIRED') }}</em></footer></article></div>
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

/* Route-family composition: sport object, research state, and evidence ledger
   form one command-center hero instead of three disconnected blocks. */
.sport-hero{position:relative;min-height:700px;padding:64px 0;display:block;overflow:hidden;border:1px solid var(--line);border-radius:22px;background:var(--contrast);isolation:isolate}.sport-hero::before{position:absolute;inset:0;background:radial-gradient(circle at 74% 42%,color-mix(in srgb,var(--sport) 15%,transparent),transparent 34%),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:auto,100px 100%;content:''}.sport-beam{position:absolute;z-index:0;left:36%;right:-12%;top:57%;height:74px;background:var(--sport);transform:rotate(-24deg);box-shadow:0 0 54px color-mix(in srgb,var(--sport) 22%,transparent)}.sport-copy{position:relative;z-index:4;width:min(62%,850px);padding:clamp(18px,4.5vw,70px)}.sport-copy h1{margin:24px 0 28px;font-size:clamp(5.2rem,9vw,9.4rem);line-height:.78;letter-spacing:-.09em}.sport-copy>p{max-width:670px;color:var(--muted-strong);font-size:16px;line-height:1.65}.sport-object{position:absolute;z-index:2;right:-2%;top:5%}.lab-state{min-height:42px;margin-top:30px;padding:10px 13px;font:700 11px 'DM Mono';background:rgba(4,7,5,.7);backdrop-filter:blur(12px)}.sport-hero aside{position:absolute;z-index:6;right:34px;bottom:30px;width:min(370px,40%);min-height:230px;padding:25px;border:1px solid color-mix(in srgb,var(--sport) 32%,var(--line));border-top:3px solid var(--sport);background:rgba(4,7,5,.82);backdrop-filter:blur(18px)}.sport-hero aside span{margin-top:auto;font:700 11px 'DM Mono'}.sport-hero aside b{margin:10px 0;font-size:30px}.sport-hero aside p{font-size:13px;line-height:1.6}.league-strip{margin-top:12px;border:1px solid var(--line);border-radius:12px;overflow:auto}.league-strip span{min-height:58px;padding:20px;font:700 12px 'DM Mono'}.architecture,.lab-page{padding:88px 0}.architecture h2,.lab-page h2{font-size:clamp(2.6rem,5vw,5rem);line-height:.95}.architecture>div,.model-cards{gap:10px;margin-top:38px;background:transparent;border:0}.architecture article,.model-cards article{min-height:310px;padding:30px;border:1px solid var(--line);border-radius:14px}.architecture article small{font:700 11px 'DM Mono'}.architecture h3,.model-cards h3{font-size:24px}.architecture p,.model-cards p,.lab-page header p{font-size:14px}.discipline-grid{gap:10px;background:transparent;border:0}.discipline-grid article{min-height:330px;border:1px solid var(--line);border-top:4px solid var(--discipline);border-radius:14px}.discipline-grid header span,.discipline-grid footer{font-size:11px}.discipline-grid p{font-size:14px}.release-gate{gap:10px;background:transparent;border:0}.release-gate>div,.release-gate ul{padding:32px;border:1px solid var(--line);border-radius:14px}.release-gate small{font:700 11px 'DM Mono'}.release-gate b{font-size:22px}.release-gate li{font-size:13px}.model-cards article>span{padding:7px 9px;font:700 11px 'DM Mono'}.model-cards dt{font:600 11px 'DM Mono'}.model-cards dd{font-size:18px}.model-cards article>footer{font:700 11px 'DM Mono'}.source-table article{min-height:86px;padding:20px}.source-table small{font:600 11px 'DM Mono'}.source-table b{font-size:15px}.source-table p{font-size:13px}.source-table em,.status-refresh,.status-error,.source-loading,.research-footer{font-size:11px}
@media(max-width:1000px){.sport-hero{min-height:720px;padding:0}.sport-copy{width:76%;padding:70px 28px}.sport-copy h1{font-size:clamp(4.8rem,11vw,7.5rem)}.sport-object{right:-22%;top:15%;opacity:.6}.sport-hero aside{right:24px;bottom:24px;width:360px}.architecture>div,.model-cards{grid-template-columns:1fr}.release-gate{grid-template-columns:1fr}}
@media(max-width:650px){.sport-hero{min-height:760px;border-radius:14px}.sport-copy{width:100%;padding:48px 20px}.sport-copy h1{font-size:clamp(3.9rem,17vw,5.8rem)}.sport-object{right:-36%;top:30%;opacity:.5}.sport-hero aside{left:18px;right:18px;bottom:18px;width:auto;min-height:210px}.league-strip span{min-width:145px}.architecture,.lab-page{padding:64px 0}}
</style>
