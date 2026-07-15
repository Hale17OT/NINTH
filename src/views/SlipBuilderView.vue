<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../services/api'
import TeamLogo from '../components/team/TeamLogo.vue'
import CustomDatePicker from '../components/ui/CustomDatePicker.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
import CustomDateRangePicker from '../components/ui/CustomDateRangePicker.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import { Check, RefreshCw, Sparkles, Trash2 } from 'lucide-vue-next'

const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
const readJson=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))||fallback}catch{return fallback}}
const BUILDER_TTL=15*60*1000
const LAST_VISIT_KEY='ninth-builder-last-visited'
const builderKeys=['ninth-slip-builder','ninth-builder-settings','ninth-builder-target']
const hasSavedBuilderState=builderKeys.some(key=>localStorage.getItem(key)!==null)
const storedLastVisit=Number(localStorage.getItem(LAST_VISIT_KEY))||(hasSavedBuilderState?Date.now():0)
if(storedLastVisit&&Date.now()-storedLastVisit>BUILDER_TTL){builderKeys.forEach(key=>localStorage.removeItem(key));localStorage.removeItem(LAST_VISIT_KEY)}
const markVisited=()=>localStorage.setItem(LAST_VISIT_KEY,String(Date.now()))
markVisited()
const savedSettings=readJson('ninth-builder-settings',{})
const date = ref(savedSettings.date||today)
const addDays=(value,amount)=>{const next=new Date(`${value}T12:00:00Z`);next.setUTCDate(next.getUTCDate()+amount);return next.toISOString().slice(0,10)}
const dateRange=ref(savedSettings.dateRange?.start&&savedSettings.dateRange?.end?savedSettings.dateRange:{start:date.value,end:addDays(date.value,2)})
const board = ref(null)
const mode = ref(savedSettings.mode==='multi'?'multi':'daily')
const targetLegs = ref(savedSettings.targetLegs||localStorage.getItem('ninth-builder-target')||'5')
const loading = ref(false)
const error = ref('')
const picks = ref(readJson('ninth-slip-builder',{}))
const legOptions=Array.from({length:9},(_,index)=>{const value=String(index+2);return{value,label:`${value} legs`,meta:index+2<=8?'Supported range':'Extended'}})
const selectedDays=computed(()=>mode.value==='daily'?1:Math.max(1,Math.min(14,Math.round((new Date(`${dateRange.value.end}T12:00:00Z`)-new Date(`${dateRange.value.start}T12:00:00Z`))/86400000)+1)))
const selectedStart=computed(()=>mode.value==='daily'?date.value:dateRange.value.start)
const legs = computed(() => (board.value?.games || []).flatMap(game => {
  const side = picks.value[String(game.game_id)]
  if (!side) return []
  return [{ ...game, side, team:game[side], probability:side === 'home' ? game.home_win_probability : game.away_win_probability }]
}))
const jointProbability = computed(() => legs.value.length ? legs.value.reduce((total, leg) => total * leg.probability, 1) : 0)
const inputAdjustedJoint = computed(() => legs.value.length ? legs.value.reduce((total,leg) => {
  const reliability=.75+.25*Number(leg.input_completeness||0)
  return total*(.5+(leg.probability-.5)*reliability)
},1) : 0)
const activeCalibration = computed(() => mode.value==='daily' ? board.value?.slip_calibration : board.value?.multiday_validation_grid?.[String(selectedDays.value)]?.[String(targetLegs.value)])
const calibrationApplies = computed(() => activeCalibration.value?.promoted!==false&&legs.value.length===Number(targetLegs.value)&&legs.value.length>=2&&legs.value.length<=8&&legs.value.every(leg=>leg.side===leg.recommended_side))
const calibratedProbability = computed(() => {
  const calibration=activeCalibration.value
  if(!legs.value.length)return 0
  if(!calibration||!calibrationApplies.value)return inputAdjustedJoint.value
  const raw=Math.min(.999999,Math.max(.000001,inputAdjustedJoint.value))
  const logit=Math.log(raw/(1-raw))
  return 1/(1+Math.exp(-(calibration.intercept+calibration.logit_slope*logit)))
})
const confidenceBand = computed(() => {
  if(!calibrationApplies.value)return null
  if(mode.value==='multi')return{observed_all_correct:activeCalibration.value.validation_observed_all_correct,wilson_low:activeCalibration.value.validation_wilson_low,wilson_high:activeCalibration.value.validation_wilson_high}
  return activeCalibration.value?.bins?.find(bin=>inputAdjustedJoint.value>=bin.raw_min&&inputAdjustedJoint.value<(bin.raw_max===1?1.0001:bin.raw_max))
})
const averageStrength = computed(() => legs.value.length ? Math.pow(jointProbability.value, 1 / legs.value.length) : 0)
const scoreLabel = computed(() => calibratedProbability.value >= .15 ? 'STRONG FOR A MULTI-LEG SLIP' : calibratedProbability.value >= .07 ? 'MODERATE COMBINATION' : legs.value.length ? 'HIGH COMBINATION RISK' : 'ADD LEGS TO SCORE')
const canRecommend = computed(() => (board.value?.games?.length||0)>=Number(targetLegs.value))
const gameDay = value => new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value))
const groupedGames = computed(() => {
  if(!board.value)return []
  if(mode.value==='daily')return [[date.value,board.value.games]]
  const groups=new Map();for(const game of board.value.games){const key=gameDay(game.starts_at);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(game)}return groups.size?[...groups]:[[dateRange.value.start,[]]]
})
const dateLabel = value => new Intl.DateTimeFormat('en-US',{weekday:'long',month:'long',day:'numeric',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`))
const timeLabel = value => new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York',timeZoneName:'short'}).format(new Date(value))
const snapshotLabel = value => value ? new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',second:'2-digit'}).format(new Date(value)) : 'pending'
const pct = value => `${(Number(value || 0)*100).toFixed(1)}%`
let loadToken=0
let refreshTimer
let mounted=false
function queueRefresh(){if(!mounted)return;window.clearTimeout(refreshTimer);refreshTimer=window.setTimeout(()=>{markVisited();load()},Math.max(3,Number(board.value?.refresh_seconds||60))*1000)}
function trimToTarget(){const limit=Number(targetLegs.value);if(legs.value.length<=limit)return;const keep=[...legs.value].sort((a,b)=>b.probability-a.probability).slice(0,limit);picks.value=Object.fromEntries(keep.map(leg=>[String(leg.game_id),leg.side]))}
async function load(){const token=++loadToken;loading.value=true;error.value='';try{const result=await api.projectionBoard(selectedStart.value,selectedDays.value);if(token!==loadToken)return;board.value=result;const available=new Set(board.value.games.map(game=>String(game.game_id)));picks.value=Object.fromEntries(Object.entries(picks.value).filter(([id])=>available.has(id)));trimToTarget()}catch(caught){if(token===loadToken)error.value=caught?.message||'The projection board could not be loaded.'}finally{if(token===loadToken){loading.value=false;queueRefresh()}}}
function select(game,side){const id=String(game.game_id);if(picks.value[id]===side){const next={...picks.value};delete next[id];picks.value=next}else if(picks.value[id]||legs.value.length<Number(targetLegs.value))picks.value={...picks.value,[id]:side}}
function recommend(){if(!canRecommend.value)return;const chosen=[...board.value.games].sort((a,b)=>b.recommended_probability-a.recommended_probability).slice(0,Number(targetLegs.value));picks.value=Object.fromEntries(chosen.map(game=>[String(game.game_id),game.recommended_side]))}
function clearSlip(){picks.value={}}
watch(picks,value=>{localStorage.setItem('ninth-slip-builder',JSON.stringify(value));markVisited()},{deep:true})
watch([date,mode,()=>dateRange.value.start,()=>dateRange.value.end],load)
watch(targetLegs,value=>{localStorage.setItem('ninth-builder-target',value);markVisited();trimToTarget()})
watch([date,mode,targetLegs,()=>dateRange.value.start,()=>dateRange.value.end],()=>{localStorage.setItem('ninth-builder-settings',JSON.stringify({date:date.value,mode:mode.value,targetLegs:targetLegs.value,dateRange:{...dateRange.value}}));markVisited()})
onMounted(()=>{mounted=true;markVisited();load()})
onBeforeUnmount(()=>{mounted=false;markVisited();window.clearTimeout(refreshTimer)})
</script>

<template>
  <div class="builder-page">
    <section class="builder-hero"><div><span class="eyebrow">NINTH / SLIP LAB</span><h1>Build {{mode==='daily'?"today's":"a multi-day"}} card.<br><em>See the real risk.</em></h1><p>Choose the number of legs, then select moneyline sides on a daily slate or across a custom date range. NINTH scores the probability that every selected leg wins using baseball-only projections—never sportsbook prices.</p></div><div class="hero-tools"><div class="mode-control"><span>SLIP TYPE</span><div><button type="button" :class="{active:mode==='daily'}" @click="mode='daily'">DAILY</button><button type="button" :class="{active:mode==='multi'}" @click="mode='multi'">MULTI-DAY</button></div></div><CustomSelect v-model="targetLegs" label="Target legs" :options="legOptions"/><CustomDatePicker v-if="mode==='daily'" v-model="date" label="Daily slate"/><CustomDateRangePicker v-else v-model="dateRange" label="Betting range" :max-days="14"/><button type="button" :disabled="loading" @click="load"><RefreshCw :class="{spin:loading}"/> REFRESH</button></div></section>
    <section class="scoreboard">
      <div class="score-ring" :style="{'--score':`${Math.min(100,calibratedProbability*100)}%`}"><span><strong class="mono">{{(calibratedProbability*100).toFixed(1)}}</strong><small>%</small></span></div>
      <div class="score-copy"><span class="eyebrow">{{calibrationApplies?'BACKTEST-ADJUSTED':'INPUT-ADJUSTED'}} SLIP CONFIDENCE</span><h2>{{scoreLabel}}</h2><p>Estimated chance that <b>all {{legs.length||0}} legs</b> win. The raw product is reduced for missing live inputs<template v-if="calibrationApplies">, then calibrated against historical {{mode==='daily'?'same-day':`${selectedDays}-day`}} walk-forward cards</template>.</p><small v-if="confidenceBand">Comparable historical cards finished together {{pct(confidenceBand.observed_all_correct)}} of the time · 95% range {{pct(confidenceBand.wilson_low)}}–{{pct(confidenceBand.wilson_high)}}</small><small v-else-if="legs.length>8">Backtest adjustment is currently supported only for 2–8 legs. Extended cards remain input-adjusted estimates.</small><small v-else-if="mode==='multi'&&activeCalibration?.promoted===false">The cross-day calibrator did not improve unseen-season Brier score, so it is deliberately not applied. This remains an input-adjusted estimate.</small><small v-else-if="mode==='multi'&&!activeCalibration&&legs.length">This custom {{selectedDays}}-day range has no validated cross-day calibrator. It remains an input-adjusted estimate rather than being mislabeled as backtested.</small><small v-else-if="legs.length">Historical calibration applies to 2–8 leg cards that follow the model pick. Custom opposing picks are shown as input-adjusted estimates, not falsely labeled as backtested.</small></div>
      <div class="score-metrics"><span><small>LEGS / TARGET</small><b class="mono">{{legs.length}} / {{targetLegs}}</b></span><span><small>{{calibrationApplies?'CALIBRATED':'ADJUSTED'}}</small><b class="mono">{{pct(calibratedProbability)}}</b></span><span><small>RAW PRODUCT</small><b class="mono">{{pct(jointProbability)}}</b></span><span><small>TYPICAL LEG</small><b class="mono">{{pct(averageStrength)}}</b></span></div>
      <div class="score-actions"><button class="recommend" type="button" :disabled="!canRecommend" @click="recommend"><Sparkles/> BUILD BEST {{targetLegs}}</button><button class="clear" type="button" :disabled="!legs.length" @click="clearSlip"><Trash2/> CLEAR</button></div>
    </section>
    <section v-if="activeCalibration" class="calibration-audit" :class="{rejected:activeCalibration.promoted===false}"><template v-if="mode==='daily'"><div><span class="eyebrow">CALIBRATION AUDIT</span><b>{{activeCalibration.training_samples.toLocaleString()}} historical same-day cards</b><small>{{activeCalibration.training_days}} walk-forward windows · 2–8 legs</small></div><div><span>UNSEEN 2025–26 BRIER</span><b class="mono">{{activeCalibration.validation_brier_calibrated.toFixed(5)}}</b><small>Raw multiplication {{activeCalibration.validation_brier_raw.toFixed(5)}}</small></div><div><span>HISTORICAL BEST-5</span><b class="mono">{{pct(activeCalibration.top_five.observed_all_correct)}}</b><small>{{activeCalibration.top_five.samples}} cards · raw predicted {{pct(activeCalibration.top_five.mean_raw)}}</small></div><p>Calibration was learned only from out-of-fold model picks. It measures model uncertainty; it does not guarantee a result or assume sportsbook odds.</p></template><template v-else><div><span class="eyebrow">{{activeCalibration.promoted?'EXACT CELL PROMOTED':'EXACT CELL NOT PROMOTED'}}</span><b>{{selectedDays}}-day × {{targetLegs}}-leg validation</b><small>{{activeCalibration.training_samples}} older cards · {{activeCalibration.validation_samples}} unseen cards</small></div><div><span>UNSEEN 2025–26 BRIER</span><b class="mono">{{activeCalibration.validation_brier_calibrated?.toFixed(5)??'—'}}</b><small>Raw multiplication {{activeCalibration.validation_brier_raw?.toFixed(5)??'—'}} · change {{activeCalibration.validation_improvement>0?'+':''}}{{activeCalibration.validation_improvement?.toFixed(5)??'—'}}</small></div><div><span>UNSEEN ALL-CORRECT RATE</span><b class="mono">{{pct(activeCalibration.validation_observed_all_correct)}}</b><small>95% range {{pct(activeCalibration.validation_wilson_low)}}–{{pct(activeCalibration.validation_wilson_high)}} · {{activeCalibration.validation_wins}} sweeps</small></div><p>{{activeCalibration.promoted?'This exact range-and-leg cell passed the aggregate and separate-year stability gates.':'This exact range-and-leg cell failed the promotion gate. Its calibration is audit-only and the displayed score remains input-adjusted.'}} <template v-if="activeCalibration.per_year">2025 change {{activeCalibration.per_year['2025']?.improvement>0?'+':''}}{{activeCalibration.per_year['2025']?.improvement?.toFixed(5)}} · 2026 change {{activeCalibration.per_year['2026']?.improvement>0?'+':''}}{{activeCalibration.per_year['2026']?.improvement?.toFixed(5)}}.</template></p></template></section>
    <LoadingState v-if="loading&&!board" label="Building the projection board" detail="Loading the slate and synchronizing every available matchup projection."/>
    <div v-else-if="error" class="state error">{{error}} <button @click="load">RETRY</button></div>
    <template v-else-if="board">
      <div v-if="board.enrichment_pending" class="board-note enriching"><span><i></i>BOARD READY · ENRICHING {{board.enrichment_pending}} MATCHUPS</span><p>Baseline projections are usable now. Confirmed lineups, starters, bullpen workload and weather are merging automatically without blocking the board.</p></div>
      <div class="board-note"><span><i></i>{{board.games.length}} UPCOMING GAMES · {{mode==='daily'?dateLabel(date).toUpperCase():`${dateLabel(dateRange.start).toUpperCase()} – ${dateLabel(dateRange.end).toUpperCase()}`}} · AUTO 60S</span><p v-if="canRecommend">“Best {{targetLegs}}” selects exactly {{targetLegs}} highest-probability games in this {{mode==='daily'?'daily slate':`${selectedDays}-day range`}}. Manual selection is capped at the same target.</p><p v-else>This slate has fewer than {{targetLegs}} upcoming games. Reduce the leg target or choose another date range.</p></div>
      <section v-for="group in groupedGames" :key="group[0]" class="day-group"><header><span class="eyebrow">SLATE DAY</span><h2>{{dateLabel(group[0])}}</h2><small>{{group[1].length}} GAMES</small></header><div class="game-grid">
        <article v-for="game in group[1]" :key="game.game_id" class="game-pick" :class="{selected:picks[String(game.game_id)]}">
          <div class="game-meta"><span>{{timeLabel(game.starts_at)}}</span><RouterLink :to="{path:`/games/${game.game_id}`,query:{from:'builder'}}">OPEN MATCHUP</RouterLink></div>
          <button type="button" :disabled="legs.length>=Number(targetLegs)&&!picks[String(game.game_id)]" :class="{active:picks[String(game.game_id)]==='away'}" @click="select(game,'away')"><TeamLogo :team="game.away" :size="42"/><span><small>AWAY MONEYLINE</small><b>{{game.away.name}}</b></span><strong class="mono">{{pct(game.away_win_probability)}}</strong><Check/></button>
          <div class="versus">VS</div>
          <button type="button" :disabled="legs.length>=Number(targetLegs)&&!picks[String(game.game_id)]" :class="{active:picks[String(game.game_id)]==='home'}" @click="select(game,'home')"><TeamLogo :team="game.home" :size="42"/><span><small>HOME MONEYLINE</small><b>{{game.home.name}}</b></span><strong class="mono">{{pct(game.home_win_probability)}}</strong><Check/></button>
          <footer><span>MODEL PICK <b>{{game[game.recommended_side].name}}</b></span><span>{{game.projection_basis==='matchup_synced'?'MATCHUP-SYNCED':'EARLY BASELINE'}} · {{snapshotLabel(game.projection_updated_at)}} · CONFIDENCE {{game.model_confidence??'—'}}/100</span></footer>
        </article>
      </div></section>
    </template>
  </div>
</template>

<style scoped>
.builder-page{display:grid;gap:14px;padding-top:20px}.builder-hero{min-height:260px;padding:36px;display:flex;align-items:flex-end;justify-content:space-between;gap:28px;border:1px solid var(--line);background:radial-gradient(circle at 80% 15%,color-mix(in srgb,var(--accent) 36%,transparent),transparent 31%),var(--surface)}h1{font-size:clamp(45px,6vw,82px);line-height:.86;letter-spacing:-.075em;margin:14px 0 20px}h1 em{font-style:normal;color:var(--acid)}.builder-hero p{max-width:630px;margin:0;color:var(--muted);font-size:11px;line-height:1.65}.hero-tools{display:flex;align-items:end;justify-content:flex-end;flex-wrap:wrap;gap:8px;flex:none;max-width:670px}.hero-tools :deep(.custom-select){width:150px}.hero-tools :deep(.date-picker){width:190px}.hero-tools :deep(.range-picker){width:285px}.hero-tools>button{height:42px;padding:0 16px;border:0;background:var(--ink);color:var(--paper);display:flex;align-items:center;gap:8px;font:700 8px 'DM Mono';cursor:pointer}.hero-tools svg{width:14px}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.mode-control{width:190px}.mode-control>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.mode-control>div{height:44px;display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);background:var(--surface);padding:3px}.mode-control button{border:0;background:transparent;font:700 7px 'DM Mono';letter-spacing:.04em;cursor:pointer;color:var(--muted)}.mode-control button.active{background:var(--ink);color:var(--accent)}
.scoreboard{display:grid;grid-template-columns:auto minmax(260px,1fr) auto auto;gap:22px;align-items:center;padding:22px 25px;background:var(--ink);color:var(--paper)}.score-ring{--score:0%;width:112px;height:112px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--accent) var(--score),#343931 0);position:relative}.score-ring:after{content:'';position:absolute;inset:8px;border-radius:50%;background:var(--ink)}.score-ring span{position:relative;z-index:1}.score-ring strong{font-size:27px}.score-ring small{font-size:9px;color:#9ca297}.score-copy h2{font-size:18px;margin:7px 0}.score-copy p{max-width:520px;font-size:9px;line-height:1.55;color:#aeb3aa;margin:0}.score-copy>small{display:block;max-width:560px;margin-top:7px;color:#d5d8d1;font:500 7px 'DM Mono';line-height:1.5}.score-copy .eyebrow{color:var(--accent)}.score-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:#343931}.score-metrics span{min-width:90px;padding:12px;background:#20241e;display:flex;flex-direction:column;gap:5px}.score-metrics small{font:500 7px 'DM Mono';color:#949a90}.score-metrics b{font-size:13px}.score-actions{display:grid;gap:7px}.score-actions button{height:42px;padding:0 14px;border:1px solid #4a5046;display:flex;align-items:center;justify-content:center;gap:7px;font:700 8px 'DM Mono';cursor:pointer}.score-actions svg{width:14px}.recommend{background:var(--accent);color:var(--ink);border-color:var(--accent)!important}.clear{background:transparent;color:var(--paper)}button:disabled{opacity:.4;cursor:not-allowed}
.calibration-audit{display:grid;grid-template-columns:repeat(3,auto) minmax(260px,1fr);align-items:center;gap:1px;border:1px solid var(--line);background:var(--line)}.calibration-audit>div,.calibration-audit>p{height:100%;padding:14px 17px;background:var(--surface);margin:0}.calibration-audit>div{display:flex;flex-direction:column;gap:4px}.calibration-audit span{font:500 7px 'DM Mono';color:var(--muted)}.calibration-audit b{font-size:12px}.calibration-audit small{font-size:8px;color:var(--muted)}.calibration-audit p{font-size:9px;line-height:1.55;color:var(--muted);display:flex;align-items:center}
.calibration-audit.rejected{border-color:color-mix(in srgb,var(--orange) 55%,var(--line))}.calibration-audit.rejected .eyebrow{color:var(--orange)}
.state{padding:45px;text-align:center;border:1px solid var(--line);background:var(--surface);font:600 9px 'DM Mono';color:var(--acid)}.state.error{color:var(--orange)}.board-note{padding:14px 17px;border:1px solid var(--line);background:var(--surface);display:flex;align-items:center;justify-content:space-between;gap:20px}.board-note span{font:600 8px 'DM Mono';white-space:nowrap}.board-note i{display:inline-block;width:7px;height:7px;margin-right:7px;background:var(--acid);border-radius:50%}.board-note p{font-size:9px;color:var(--muted);margin:0;max-width:760px;text-align:right}.day-group{border:1px solid var(--line);background:var(--surface)}.day-group>header{display:grid;grid-template-columns:1fr auto;align-items:end;padding:16px 18px;border-bottom:1px solid var(--line)}.day-group>header .eyebrow{grid-column:1}.day-group>header h2{font-size:18px;margin:5px 0 0}.day-group>header small{grid-column:2;grid-row:1/3;font:600 8px 'DM Mono';color:var(--muted)}.game-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:10px}.game-pick{border:1px solid var(--line);background:var(--wash);padding:10px}.game-pick.selected{border-color:var(--ink)}.game-meta,.game-pick footer{display:flex;justify-content:space-between;gap:10px;font:600 7px 'DM Mono';color:var(--muted)}.game-meta{padding:2px 4px 9px}.game-meta a{text-decoration:none;border-bottom:1px solid}.game-pick>button{width:100%;min-height:69px;display:grid;grid-template-columns:auto minmax(0,1fr) auto 17px;align-items:center;gap:10px;text-align:left;padding:8px;border:1px solid transparent;background:var(--surface);cursor:pointer}.game-pick>button:hover{border-color:var(--muted)}.game-pick>button.active{border-color:var(--ink);background:color-mix(in srgb,var(--accent) 28%,var(--surface))}.game-pick>button span{display:flex;flex-direction:column;min-width:0}.game-pick>button small{font:500 7px 'DM Mono';color:var(--muted)}.game-pick>button b{font-size:11px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.game-pick>button strong{font-size:15px}.game-pick>button svg{width:15px;opacity:0}.game-pick>button.active svg{opacity:1}.versus{text-align:center;font:600 7px 'DM Mono';color:var(--muted);height:18px;line-height:18px}.game-pick footer{padding:10px 4px 1px;border-top:1px solid var(--line);margin-top:9px}.game-pick footer b{color:var(--text)}
@media(max-width:1100px){.scoreboard{grid-template-columns:auto 1fr}.score-metrics,.score-actions{grid-column:2}.score-actions{grid-template-columns:1fr 1fr}.game-grid{grid-template-columns:1fr}.calibration-audit{grid-template-columns:repeat(3,1fr)}.calibration-audit>p{grid-column:1/-1}}@media(max-width:700px){.builder-hero{padding:25px;align-items:flex-start;flex-direction:column}.hero-tools{width:100%;flex-wrap:wrap}.mode-control{width:100%}.hero-tools :deep(.date-picker),.hero-tools :deep(.range-picker){flex:1;width:100%}.scoreboard{grid-template-columns:1fr;text-align:center}.score-ring{margin:auto}.score-metrics,.score-actions{grid-column:1}.score-copy p{margin:auto}.board-note{align-items:flex-start;flex-direction:column}.board-note p{text-align:left}.game-pick footer{flex-direction:column}.game-pick>button{grid-template-columns:auto minmax(0,1fr) auto 15px}.calibration-audit{grid-template-columns:1fr}.calibration-audit>p{grid-column:1}}
.calibration-audit{display:none}.scoreboard{background:var(--contrast);color:var(--on-contrast)}.score-ring:after{background:var(--contrast)}.clear{color:var(--on-contrast)}.recommend{color:var(--selection-text)}.game-pick>button.active{background:var(--selection-bg);color:var(--selection-text);border-color:color-mix(in srgb,var(--selection-text) 55%,var(--selection-bg))}.game-pick>button.active small{color:var(--selection-muted)}.game-pick>button.active b,.game-pick>button.active strong,.game-pick>button.active svg{color:var(--selection-text)}
</style>
