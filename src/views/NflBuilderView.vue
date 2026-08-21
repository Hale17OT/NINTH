<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, Check, CircleGauge, LockKeyhole, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion-v'
import { api } from '../services/api'
import SportIdentity from '../components/identity/SportIdentity.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
import UnifiedBuilderHero from '../components/builder/UnifiedBuilderHero.vue'
import UnifiedBuilderScore from '../components/builder/UnifiedBuilderScore.vue'
import { independentEventJointProbability } from '../domain/cardMath'

const loading = ref(true), error = ref(''), payload = ref(null)
const marketMode = ref('moneyline'), evidenceMode = ref('shadow'), selectedWeek = ref('')
const target = ref(5), minimumOdds = ref('all'), minimumProbability=ref('all'), minimumEdge=ref('all'), selected = ref([])
const reduced = useReducedMotion()
const allScheduled = computed(() => (payload.value?.items || []).filter(game => game.status === 'Scheduled' && game.prediction))
const weekNumber = game => String(game.round || '').match(/WEEK\s+(\d+)/i)?.[1] || '—'
const availableWeeks = computed(() => [...new Set(allScheduled.value.map(weekNumber))].sort((a,b) => Number(a)-Number(b)))
const scheduled = computed(() => allScheduled.value.filter(game => weekNumber(game) === selectedWeek.value))
const marketDefinitions = prediction => {
  const line = Number(prediction.total_line), spread = Number(prediction.spread_line), values = []
  const home = Number(prediction.markets?.home_win || 0), away = Number(prediction.markets?.away_win || 0)
  const moneylineKey=home>=away?'home_moneyline':'away_moneyline'
  values.push({ market:'moneyline', side:home>=away?'home':'away', probability:Math.max(home,away), odds:Number(prediction.prices?.[moneylineKey])||null, fairOdds:Number(prediction.fair_odds?.[moneylineKey])||null, noVig:Number(prediction.no_vig_market_probability?.[moneylineKey])||null, edge:Number.isFinite(Number(prediction.edge?.[moneylineKey]))?Number(prediction.edge[moneylineKey]):null, eligible:prediction.market_eligibility?.moneyline===true, consensus:prediction.model_consensus?.moneyline!==false })
  if(Number.isFinite(spread)&&prediction.markets?.home_spread!=null){const h=Number(prediction.markets.home_spread),a=Number(prediction.markets.away_spread),key=h>=a?'home_spread':'away_spread';values.push({market:'spread',side:h>=a?'home':'away',line:spread,probability:Math.max(h,a),odds:Number(prediction.prices?.[key])||null,fairOdds:Number(prediction.fair_odds?.[key])||null,noVig:Number(prediction.no_vig_market_probability?.[key])||null,edge:Number.isFinite(Number(prediction.edge?.[key]))?Number(prediction.edge[key]):null,eligible:prediction.market_eligibility?.spread===true,consensus:true})}
  if(Number.isFinite(line)&&prediction.markets?.over_total!=null){const over=Number(prediction.markets.over_total),under=Number(prediction.markets.under_total),key=over>=under?'over_total':'under_total';values.push({market:'total',side:over>=under?'over':'under',line,probability:Math.max(over,under),odds:Number(prediction.prices?.[key])||null,fairOdds:Number(prediction.fair_odds?.[key])||null,noVig:Number(prediction.no_vig_market_probability?.[key])||null,edge:Number.isFinite(Number(prediction.edge?.[key]))?Number(prediction.edge[key]):null,eligible:prediction.market_eligibility?.total===true,consensus:true})}
  return values
}
const allCandidates = computed(() => scheduled.value.flatMap(game => marketDefinitions(game.prediction).map(option => ({id:`${game.id}:${option.market}:${option.side}`,game,option}))))
const candidates = computed(() => allCandidates.value.filter(row=>marketMode.value==='mixed'||row.option.market===marketMode.value).filter(row=>evidenceMode.value!=='production'||row.option.eligible).filter(row=>minimumOdds.value==='all'||(row.option.odds&&row.option.odds>=Number(minimumOdds.value))).filter(row=>minimumProbability.value==='all'||row.option.probability>=Number(minimumProbability.value)).filter(row=>minimumEdge.value==='all'||(row.option.edge!=null&&row.option.edge>=Number(minimumEdge.value))).sort((a,b)=>b.option.probability-a.option.probability))
const selectedIds = computed(()=>new Set(selected.value.map(row=>row.id))), occupied = computed(()=>new Set(selected.value.map(row=>String(row.game.id))))
const jointProbability = computed(()=>independentEventJointProbability(selected.value))
const averageProbability = computed(()=>selected.value.length?selected.value.reduce((sum,row)=>sum+row.option.probability,0)/selected.value.length:0)
const combinedOdds = computed(()=>selected.value.length&&selected.value.every(row=>row.option.odds)?selected.value.reduce((product,row)=>product*row.option.odds,1):null)
const readiness = computed(()=>scheduled.value[0]?.prediction?.readiness||{})
const marketOptions=[{value:'moneyline',label:'MONEYLINE'},{value:'spread',label:'SPREAD'},{value:'total',label:'TOTALS'},{value:'mixed',label:'MIXED'}]
const evidenceOptions=[{value:'shadow',label:'All forecasts',meta:'Model board'},{value:'production',label:'Builder eligible',meta:'Audited only'}]
const targetOptions=Array.from({length:9},(_,index)=>({value:index+2,label:`${index+2} legs`}))
const oddsOptions=[{value:'all',label:'All listed odds'},...[1.2,1.3,1.4,1.5,1.75,2].map(value=>({value:String(value),label:`${value}+`}))]
const probabilityOptions=[{value:'all',label:'Any probability'},...[.55,.60,.65,.70].map(value=>({value:String(value),label:`${Math.round(value*100)}%+`}))]
const edgeOptions=[{value:'all',label:'Any / unavailable'},...[.02,.04,.06,.08].map(value=>({value:String(value),label:`${Math.round(value*100)}%+ edge`}))]
const weekOptions=computed(()=>availableWeeks.value.map(value=>({value,label:`Week ${value}`})))
const teamName=(game,side)=>game[side]?.name||side
const selectionLabel=row=>{const{game,option}=row;if(option.market==='moneyline')return`${teamName(game,option.side)} moneyline`;if(option.market==='total')return`${option.side.toUpperCase()} ${option.line}`;const displayed=option.side==='home'?-Number(option.line):Number(option.line);return`${teamName(game,option.side)} ${displayed>0?'+':''}${displayed}`}
const marketLabel=market=>({moneyline:'Moneyline',spread:'Spread',total:'Total points'}[market]||market)
const formatProbability=value=>`${(Number(value||0)*100).toFixed(1)}%`
const eventLabel=game=>`${game.away?.name} @ ${game.home?.name}`
const scoreLabel=game=>{const score=game.prediction?.expected_score;return score?`${Number(score.away).toFixed(1)}–${Number(score.home).toFixed(1)} projected`:'Score distribution pending'}
const toggle=row=>{if(selectedIds.value.has(row.id)){selected.value=selected.value.filter(item=>item.id!==row.id);return}if(occupied.value.has(String(row.game.id))||selected.value.length>=Number(target.value))return;selected.value=[...selected.value,row]}
const buildBest=()=>{const picks=[],games=new Set(),exposure=new Map(),cap=marketMode.value==='mixed'?(Number(target.value)<=5?2:3):Number(target.value);for(const row of candidates.value){const gameId=String(row.game.id),key=`${row.option.market}:${row.option.side}`;if(games.has(gameId)||(exposure.get(key)||0)>=cap)continue;if(row.option.market==='moneyline'&&!row.option.consensus)continue;picks.push(row);games.add(gameId);exposure.set(key,(exposure.get(key)||0)+1);if(picks.length>=Number(target.value))break}selected.value=picks}
const load=async()=>{loading.value=true;error.value='';try{payload.value=await api.sportDirectory('american-football','games',{season:new Date().getUTCFullYear()});const weeks=availableWeeks.value;if(!selectedWeek.value||(selectedWeek.value!=='all'&&!weeks.includes(selectedWeek.value)))selectedWeek.value=weeks[0]||'all'}catch(caught){error.value=caught?.message||'NFL slate could not be loaded.'}finally{loading.value=false}}
watch([marketMode,evidenceMode,selectedWeek,minimumOdds,minimumProbability,minimumEdge,target],()=>{selected.value=[]})
onMounted(load)
</script>

<template>
  <div class="unified-builder nfl-builder">
    <UnifiedBuilderHero eyebrow="NINTH / NFL BUILDER" title="Build today's" accent="NFL card." description="Moneyline, spread and total-points decisions use the same compact card-building flow as MLB while every NFL market retains its own evidence gate.">
      <div class="builder-segment"><small>MODEL</small><div><button v-for="option in marketOptions" :key="option.value" :class="{active:marketMode===option.value}" @click="marketMode=option.value">{{option.label}}</button></div></div>
      <div class="builder-control-bar"><CustomSelect v-model="evidenceMode" label="Evidence" :options="evidenceOptions"/><CustomSelect v-model="selectedWeek" label="Slate" :options="weekOptions"/><CustomSelect v-model="target" label="Target legs" :options="targetOptions"/><CustomSelect v-model="minimumOdds" label="Odds floor" :options="oddsOptions"/><CustomSelect v-model="minimumProbability" label="Probability" :options="probabilityOptions"/><CustomSelect v-model="minimumEdge" label="Edge" :options="edgeOptions"/><button class="builder-refresh" :disabled="loading" @click="load"><RefreshCw :class="{spin:loading}"/> REFRESH</button></div>
    </UnifiedBuilderHero>
    <UnifiedBuilderScore :probability="jointProbability" :selected="selected.length" :target="Number(target)" :average="averageProbability" :title="selected.length ? `${selected.length}-leg NFL card` : 'No NFL legs selected'" description="The displayed joint estimate multiplies probabilities only across different games. One selection is allowed per game and mixed cards cap repeated market-side exposure." :detail="combinedOdds ? `Current combined decimal price ${combinedOdds.toFixed(2)}. Prices filter and describe selections; they are not model inputs.` : 'Current prices appear when the source feed lists them.'" fourth-label="EVIDENCE" :fourth-value="evidenceMode==='production'?'ELIGIBLE':'ALL'">
      <template #actions><button class="primary" :disabled="loading||!candidates.length" @click="buildBest"><CircleGauge/> BUILD BEST {{target}}</button><button :disabled="!selected.length" @click="selected=[]"><Trash2/> CLEAR</button></template>
    </UnifiedBuilderScore>
    <section class="builder-model-strip"><article v-for="market in ['moneyline','spread','total']" :key="market" :class="{ready:readiness.historical?.[market]}"><span>{{marketLabel(market)}}</span><b>{{readiness.historical?.[market]?'HISTORICAL EVIDENCE':'MORE EVIDENCE REQUIRED'}}</b><small>{{readiness.live?.[market]?.samples||0}} / 30 RECENT · BRIER {{readiness.live?.[market]?.brier?.toFixed(3)||'—'}}</small></article></section>
    <section class="builder-board-note"><span><i></i>{{candidates.length}} CURRENT NFL LINES · WEEK {{selectedWeek}}</span><p>Builder eligible shows only markets that pass their evidence gate. The full board remains analytical and never triggers sportsbook autofill by itself.</p></section>
    <div v-if="selected.length" class="builder-selected-summary"><AnimatePresence mode="popLayout"><motion.article v-for="(row,index) in selected" :key="row.id" layout :initial="reduced?false:{opacity:0,y:10}" :animate="{opacity:1,y:0}" :exit="reduced?undefined:{opacity:0,scale:.97}"><span>{{String(index+1).padStart(2,'0')}}</span><div><small>{{marketLabel(row.option.market)}} · {{formatProbability(row.option.probability)}}</small><b>{{selectionLabel(row)}}</b><em>{{eventLabel(row.game)}}</em></div><button @click="toggle(row)">×</button></motion.article></AnimatePresence></div>
    <section class="builder-day"><header><div><span class="eyebrow">CURRENT NFL BOARD</span><h2>{{candidates.length}} decision-ready lines</h2></div><small>{{scheduled.length}} GAMES</small></header>
      <div v-if="loading" class="builder-state"><RefreshCw class="spin"/><b>Loading NFL distributions</b><p>Joining the schedule, current prices, EPA history and immutable audit state.</p></div>
      <div v-else-if="error" class="builder-state"><AlertTriangle/><b>NFL board unavailable</b><p>{{error}}</p></div>
      <div v-else-if="!candidates.length" class="builder-state"><LockKeyhole/><b>No markets pass these controls</b><p>Switch to all model forecasts or widen the odds floor to inspect the available board.</p></div>
      <LayoutGroup v-else id="nfl-builder"><motion.div layout class="builder-card-grid"><AnimatePresence mode="popLayout"><motion.article v-for="row in candidates" :key="row.id" layout class="builder-choice-card" :class="{selected:selectedIds.has(row.id)}" :initial="reduced?false:{opacity:0,y:12}" :animate="{opacity:1,y:0}" :exit="reduced?undefined:{opacity:0,scale:.98}" :while-hover="reduced?undefined:{y:-2}">
        <div class="builder-card-meta"><span>W{{weekNumber(row.game)}} · {{row.game.date}}</span><strong>{{row.option.eligible?'BUILDER ELIGIBLE':'MODEL FORECAST'}}</strong></div>
        <div class="builder-matchup"><div class="builder-team"><SportIdentity :identity="row.game.away" :size="38" square/><span><small>AWAY</small><b>{{row.game.away?.name}}</b></span></div><i class="builder-versus">AT</i><div class="builder-team home"><SportIdentity :identity="row.game.home" :size="38" square/><span><small>HOME</small><b>{{row.game.home?.name}}</b></span></div></div>
        <div class="builder-market-label">{{marketLabel(row.option.market)}}<span>{{scoreLabel(row.game)}}</span></div>
        <button class="builder-selection" :class="{active:selectedIds.has(row.id)}" :disabled="(!selectedIds.has(row.id)&&occupied.has(String(row.game.id)))||(!selectedIds.has(row.id)&&selected.length>=Number(target))" @click="toggle(row)"><span><small>{{row.option.side.toUpperCase()}} · {{row.option.odds?`MARKET @ ${row.option.odds.toFixed(3)}`:'PRICE PENDING'}} · {{row.option.fairOdds?`FAIR @ ${row.option.fairOdds.toFixed(3)}`:'FAIR —'}}</small><b>{{selectionLabel(row)}}</b></span><strong>{{formatProbability(row.option.probability)}}</strong><Check v-if="selectedIds.has(row.id)"/><Plus v-else/></button>
        <footer class="builder-card-footer"><span>{{row.option.consensus?'MODEL CONSISTENT':'MODEL DISAGREEMENT'}} · {{row.option.edge==null?'NO EDGE DATA':`NO-VIG ${formatProbability(row.option.noVig)} / EDGE ${row.option.edge>=0?'+':''}${formatProbability(row.option.edge)}`}}</span><b>ONE PICK PER GAME</b></footer>
      </motion.article></AnimatePresence></motion.div></LayoutGroup>
    </section>
  </div>
</template>

<style scoped>.nfl-builder{--sport:#83a8ff}.builder-control-bar{grid-template-columns:repeat(3,minmax(0,1fr))}.builder-refresh{grid-column:1/-1}.builder-control-bar :deep(.custom-select){min-width:0}.builder-control-bar :deep(.select-label){font-size:11px}.builder-control-bar :deep(.trigger){min-height:48px}@media(max-width:650px){.builder-control-bar{grid-template-columns:1fr 1fr}}@media(max-width:450px){.builder-control-bar{grid-template-columns:1fr}}</style>
