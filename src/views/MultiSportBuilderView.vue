<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, Check, Layers3, LockKeyhole, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion-v'
import { api } from '../services/api'
import { sports } from '../config/sports'
import SportIdentity from '../components/identity/SportIdentity.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
import UnifiedBuilderHero from '../components/builder/UnifiedBuilderHero.vue'
import UnifiedBuilderScore from '../components/builder/UnifiedBuilderScore.vue'

const loading = ref(true)
const error = ref('')
const board = ref(null)
const researchBoards = ref({ football: [], 'american-football': [], basketball: [], esports: [] })
const activeSport = ref('all')
const viewMode = ref('production')
const target = ref(5)
const minimumOdds = ref('all')
const selected = ref([])
const reduced = useReducedMotion()
const today = () => {
  const date = new Date(), offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 10)
}
const sportState = sport => sport.id === 'baseball' ? 'LIVE BOARD' : researchBoards.value[sport.id]?.some(game => game.prediction) ? 'SHADOW BOARD' : 'RESEARCH LOCKED'
const productionCandidates = computed(() => (board.value?.games || []).flatMap(game => {
  const rows = []
  if (game.automatic_moneyline_eligible && game.recommended_side && game.recommended_probability) {
    const side = game.recommended_side, team = game[side]
    rows.push({ id:`mlb:${game.game_id}:moneyline:${side}`, sport:'baseball', sportLabel:'MLB', gameId:game.game_id, game, event:`${game.away.name} @ ${game.home.name}`, startsAt:game.starts_at, market:'Moneyline', selection:`${team.name} to win`, probability:Number(game.recommended_probability), odds:Number(game.moneyline_odds?.[side]||0), evidence:'PRODUCTION ELIGIBLE' })
  }
  const total = game.totals_projection
  if (total?.automatic_builder_eligible && total.recommended_line && total.recommended_side) {
    const threshold = (total.thresholds || []).find(row => Number(row.line) === Number(total.recommended_line))
    rows.push({ id:`mlb:${game.game_id}:total:${total.recommended_side}:${total.recommended_line}`, sport:'baseball', sportLabel:'MLB', gameId:game.game_id, game, event:`${game.away.name} @ ${game.home.name}`, startsAt:game.starts_at, market:'Total runs', selection:`${total.recommended_side.toUpperCase()} ${total.recommended_line}`, probability:Number(total.recommended_probability), odds:Number(threshold?.melbet_odds?.[total.recommended_side]||0), evidence:'PRODUCTION ELIGIBLE' })
  }
  return rows
}).sort((a,b) => b.probability-a.probability))
const shadowCandidates = computed(() => Object.entries(researchBoards.value).flatMap(([sport, games]) => games.flatMap(game => {
  const prediction = game.prediction
  if (!prediction?.markets) return []
  if (sport === 'football') {
    const strongest = [['home_win',game.home?.name,'1'],['draw','Draw','X'],['away_win',game.away?.name,'2']].map(([key,name,code])=>({key,name,code,probability:Number(prediction.markets[key]||0)})).sort((a,b)=>b.probability-a.probability)[0]
    return [{ id:`${sport}:${game.id}:1x2:${strongest.key}`, sport, sportLabel:'FTB', gameId:game.id, game, event:`${game.away?.name} @ ${game.home?.name}`, startsAt:game.timestamp||`${game.date}T${game.time}`, market:'1X2', selection:`${strongest.code} · ${strongest.name}`, probability:strongest.probability, odds:0, evidence:'SHADOW ONLY · NOT WAGER ELIGIBLE' }]
  }
  if (sport === 'american-football') {
    const home=Number(prediction.markets.home_win||0), away=Number(prediction.markets.away_win||0), useHome=home>=away
    return [{ id:`${sport}:${game.id}:moneyline:${useHome?'home':'away'}`, sport, sportLabel:'NFL', gameId:game.id, game, event:`${game.away?.name} @ ${game.home?.name}`, startsAt:game.timestamp||`${game.date}T${game.time}`, market:'Moneyline', selection:`${useHome?game.home?.name:game.away?.name} to win`, probability:useHome?home:away, odds:0, evidence:'SHADOW ONLY · NOT WAGER ELIGIBLE' }]
  }
  if (sport === 'esports') {
    const home=Number(prediction.markets.home_win||0), away=Number(prediction.markets.away_win||0), useHome=home>=away
    return [{ id:`${sport}:${game.id}:match-winner:${useHome?'home':'away'}`, sport, sportLabel:game.competitionCode||'ESP', gameId:game.id, game, event:`${game.away?.name} vs ${game.home?.name}`, startsAt:game.timestamp||`${game.date}T${game.time}`, market:'Match winner', selection:`${useHome?game.home?.name:game.away?.name} to win`, probability:useHome?home:away, odds:0, evidence:`${prediction.modelStatus||'LIVE SHADOW'} · NOT WAGER ELIGIBLE` }]
  }
  return []
})).sort((a,b)=>b.probability-a.probability))
const allModeCandidates = computed(() => viewMode.value === 'production' ? productionCandidates.value : [...productionCandidates.value,...shadowCandidates.value].sort((a,b)=>b.probability-a.probability))
const candidates = computed(() => allModeCandidates.value.filter(row=>minimumOdds.value==='all'||(row.odds&&row.odds>=Number(minimumOdds.value))))
const visible = computed(() => activeSport.value === 'all' ? candidates.value : candidates.value.filter(row=>row.sport===activeSport.value))
const selectedIds = computed(() => new Set(selected.value.map(row=>row.id)))
const occupiedEvents = computed(() => new Set(selected.value.map(row=>`${row.sport}:${row.gameId}`)))
const jointProbability = computed(() => selected.value.reduce((product,row)=>product*row.probability,1))
const averageProbability = computed(() => selected.value.length?selected.value.reduce((sum,row)=>sum+row.probability,0)/selected.value.length:0)
const combinedOdds = computed(() => selected.value.length&&selected.value.every(row=>row.odds>0)?selected.value.reduce((product,row)=>product*row.odds,1):null)
const targetOptions = Array.from({length:14},(_,index)=>({value:index+2,label:`${index+2} legs`}))
const evidenceOptions = [{value:'production',label:'Production eligible',meta:'Audited only'},{value:'shadow',label:'Research shadow',meta:'Preview locked models'}]
const oddsOptions = [{value:'all',label:'All listed odds'},...[1.2,1.3,1.4,1.5,1.75,2].map(value=>({value:String(value),label:`${value}+`}))]
const formatProbability = value => `${(Number(value||0)*100).toFixed(1)}%`
const accentFor = sportId => sports.find(item=>item.id===sportId)?.accent || '#c7f04b'
const toggle = row => {
  if (selectedIds.value.has(row.id)) { selected.value=selected.value.filter(item=>item.id!==row.id); return }
  if (occupiedEvents.value.has(`${row.sport}:${row.gameId}`)||selected.value.length>=Number(target.value)) return
  selected.value=[...selected.value,row]
}
const buildBest = () => {
  const picked=[], events=new Set(), sportExposure=new Map(), availableSports=new Set(visible.value.map(row=>row.sport)).size
  for (const row of visible.value) {
    const event=`${row.sport}:${row.gameId}`, cap=activeSport.value==='all'&&availableSports>1?Math.max(1,Math.ceil(Number(target.value)/3)):Number(target.value)
    if(events.has(event)||(sportExposure.get(row.sport)||0)>=cap)continue
    picked.push(row);events.add(event);sportExposure.set(row.sport,(sportExposure.get(row.sport)||0)+1)
    if(picked.length>=Number(target.value))break
  }
  selected.value=picked
}
const setMode = mode => { viewMode.value=mode; selected.value=[]; minimumOdds.value='all' }
const load = async () => {
  loading.value=true;error.value=''
  try {
    const [production,football,nfl,basketball,esports]=await Promise.all([api.projectionBoard(today(),1),api.sportDirectory('football','games'),api.sportDirectory('american-football','games'),api.sportDirectory('basketball','games'),api.sportDirectory('esports','games')])
    board.value=production
    researchBoards.value={football:football.items||[],'american-football':nfl.items||[],basketball:basketball.items||[],esports:esports.items||[]}
  } catch(caught) { error.value=caught?.message||'The combined board could not be loaded.' }
  finally { loading.value=false }
}
watch([activeSport,target,minimumOdds],()=>{selected.value=[]})
onMounted(load)
</script>

<template>
  <div class="unified-builder multi-builder">
    <UnifiedBuilderHero eyebrow="NINTH / ALL-SPORTS BUILDER" title="One card." accent="Every arena." description="Build one portfolio from sport-native forecasts without blending their evidence. Each leg retains its own release state, event identity and probability contract.">
      <div class="builder-segment sport-filter"><small>SPORT</small><div><button :class="{active:activeSport==='all'}" @click="activeSport='all'">ALL</button><button v-for="sport in sports" :key="sport.id" :style="{'--lane':sport.accent}" :class="{active:activeSport===sport.id}" @click="activeSport=sport.id">{{sport.short}}</button></div></div>
      <div class="builder-control-bar"><CustomSelect :model-value="viewMode" label="Evidence" :options="evidenceOptions" @update:model-value="setMode"/><CustomSelect v-model="target" label="Target legs" :options="targetOptions"/><CustomSelect v-model="minimumOdds" label="Odds floor" :options="oddsOptions"/><button class="builder-refresh" :disabled="loading" @click="load"><RefreshCw :class="{spin:loading}"/> REFRESH</button></div>
    </UnifiedBuilderHero>

    <UnifiedBuilderScore :probability="jointProbability" :selected="selected.length" :target="Number(target)" :average="averageProbability" :title="selected.length?`${selected.length}-leg combined card`:'No combined legs selected'" description="The joint score multiplies the selected sport-native probabilities. One selection is allowed per event and cross-sport builds cap concentration in any one model family." :detail="combinedOdds?`Current combined decimal price ${combinedOdds.toFixed(2)}. Research-only legs never become wager eligible.`:'Combined price appears only when every selected leg has a current listed price.'" fourth-label="EVIDENCE" :fourth-value="viewMode==='production'?'AUTO':'SHADOW'">
      <template #actions><button class="primary" :disabled="loading||!visible.length" @click="buildBest"><Layers3/> BUILD BEST {{target}}</button><button :disabled="!selected.length" @click="selected=[]"><Trash2/> CLEAR</button></template>
    </UnifiedBuilderScore>

    <section class="builder-model-strip"><article v-for="sport in sports" :key="sport.id" :class="{ready:sport.id==='baseball'}" :style="{'--sport':sport.accent}"><span>{{sport.name}}</span><b>{{sportState(sport)}}</b><small>{{sport.id==='baseball'?`${productionCandidates.length} automatic legs`:`${researchBoards[sport.id]?.filter(game=>game.prediction).length||0} exact-event forecasts`}}</small></article></section>
    <section class="builder-board-note"><span><i></i>{{visible.length}} VISIBLE LINES · {{viewMode==='production'?'AUDITED RELEASE':'RESEARCH PREVIEW'}}</span><p>Combined does not mean blended: probabilities stay attached to their sport-native model, and locked sports remain visibly research-only.</p></section>

    <div v-if="selected.length" class="builder-selected-summary"><AnimatePresence mode="popLayout"><motion.article v-for="(row,index) in selected" :key="row.id" layout :style="{'--sport':accentFor(row.sport)}" :initial="reduced?false:{opacity:0,y:10}" :animate="{opacity:1,y:0}" :exit="reduced?undefined:{opacity:0,scale:.97}"><span>{{String(index+1).padStart(2,'0')}}</span><div><small>{{row.sportLabel}} · {{row.market}} · {{formatProbability(row.probability)}}</small><b>{{row.selection}}</b><em>{{row.event}}</em></div><button @click="toggle(row)">×</button></motion.article></AnimatePresence></div>

    <section class="builder-day"><header><div><span class="eyebrow">{{viewMode==='production'?'AUDITED INVENTORY':'CROSS-SPORT RESEARCH INVENTORY'}}</span><h2>{{visible.length}} decision-ready outcomes</h2></div><small>{{activeSport==='all'?'ALL SPORTS':sports.find(item=>item.id===activeSport)?.name}}</small></header>
      <div v-if="loading" class="builder-state"><RefreshCw class="spin"/><b>Syncing sport adapters</b><p>Joining current immutable production and research boards.</p></div>
      <div v-else-if="error" class="builder-state"><AlertTriangle/><b>Combined board unavailable</b><p>{{error}}</p></div>
      <div v-else-if="viewMode==='production'&&activeSport!=='all'&&activeSport!=='baseball'" class="builder-state"><LockKeyhole/><b>{{sports.find(item=>item.id===activeSport)?.name}} is evidence-locked</b><p>Switch to Research shadow to inspect exact-event forecasts without making them wager eligible.</p></div>
      <div v-else-if="!visible.length" class="builder-state"><AlertTriangle/><b>No outcomes pass these controls</b><p>Widen the odds floor, change sport, or inspect shadow forecasts. No manual-only signal is substituted.</p></div>
      <LayoutGroup v-else id="multi-sport-builder"><motion.div layout class="builder-card-grid"><AnimatePresence mode="popLayout"><motion.article v-for="row in visible" :key="row.id" layout class="builder-choice-card" :style="{'--sport':accentFor(row.sport)}" :class="{selected:selectedIds.has(row.id)}" :initial="reduced?false:{opacity:0,y:12}" :animate="{opacity:1,y:0}" :exit="reduced?undefined:{opacity:0,scale:.98}" :while-hover="reduced?undefined:{y:-2}">
        <div class="builder-card-meta"><span>{{row.startsAt||'Start time pending'}}</span><strong>{{row.evidence}}</strong></div>
        <div class="builder-matchup"><div class="builder-team"><SportIdentity :identity="row.game.away" :size="38"/><span><small>{{row.sport==='esports'?'SIDE A':'AWAY'}}</small><b>{{row.game.away?.name}}</b></span></div><i class="builder-versus">{{row.sport==='esports'?'VS':'AT'}}</i><div class="builder-team home"><SportIdentity :identity="row.game.home" :size="38"/><span><small>{{row.sport==='esports'?'SIDE B':'HOME'}}</small><b>{{row.game.home?.name}}</b></span></div></div>
        <div class="builder-market-label">{{row.market}}<span>{{row.sportLabel}}</span></div>
        <button class="builder-selection" :class="{active:selectedIds.has(row.id)}" :disabled="!selectedIds.has(row.id)&&(occupiedEvents.has(`${row.sport}:${row.gameId}`)||selected.length>=Number(target))" @click="toggle(row)"><span><small>{{row.odds?`CURRENT PRICE @ ${row.odds.toFixed(3)}`:'PRICE PENDING'}}</small><b>{{row.selection}}</b></span><strong>{{formatProbability(row.probability)}}</strong><Check v-if="selectedIds.has(row.id)"/><Plus v-else/></button>
        <footer class="builder-card-footer"><span>{{row.evidence}}</span><b>ONE PICK PER EVENT</b></footer>
      </motion.article></AnimatePresence></motion.div></LayoutGroup>
    </section>
  </div>
</template>

<style scoped>
.multi-builder{--sport:#c7f04b}.builder-control-bar{grid-template-columns:minmax(190px,1fr) minmax(130px,.7fr) minmax(150px,.8fr) auto}.sport-filter>div{grid-auto-flow:column}.sport-filter button{border-bottom:2px solid transparent}.sport-filter button.active{border-color:var(--lane,var(--sport))}.builder-card-meta strong{max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}@media(max-width:850px){.builder-control-bar{grid-template-columns:1fr 1fr}.sport-filter>div{grid-auto-flow:row;grid-template-columns:repeat(3,1fr)}}@media(max-width:480px){.builder-control-bar{grid-template-columns:1fr}.sport-filter>div{grid-template-columns:repeat(2,1fr)}}
</style>
