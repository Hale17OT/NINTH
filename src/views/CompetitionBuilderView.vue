<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, Check, LockKeyhole, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-vue-next'
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion-v'
import { useRoute, useRouter } from 'vue-router'
import SportIdentity from '../components/identity/SportIdentity.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
import UnifiedBuilderHero from '../components/builder/UnifiedBuilderHero.vue'
import UnifiedBuilderScore from '../components/builder/UnifiedBuilderScore.vue'
import { gamePrediction, probability, sentenceCase, sportLabel } from '../domain/sports'
import { sportById } from '../config/sports'
import { api } from '../services/api'

const props=defineProps({sport:{type:String,required:true}}),route=useRoute(),router=useRouter(),reduced=useReducedMotion()
const leagues=ref([]),games=ref([]),loading=ref(true),error=ref(''),selected=ref([]),target=ref(5),evidenceMode=ref('shadow'),marketMode=ref('all')
const active=computed(()=>sportById(props.sport)),competition=computed(()=>String(route.query.competition||'')),league=computed(()=>leagues.value.find(row=>String(row.id)===competition.value)||null)
const allCandidates=computed(()=>games.value.flatMap(game=>Object.entries(game.prediction?.markets||{}).filter(([,value])=>Number(value)>=.5).map(([market,value])=>({id:`${game.id}:${market}`,game,market,probability:Number(value),eligible:game.prediction?.market_eligibility?.[market]===true,label:gamePrediction({...game,prediction:{...game.prediction,markets:{[market]:value}}})?.label||sentenceCase(market)}))).sort((a,b)=>Number(b.eligible)-Number(a.eligible)||b.probability-a.probability))
const marketKeys=computed(()=>[...new Set(allCandidates.value.map(row=>row.market))])
const candidates=computed(()=>allCandidates.value.filter(row=>marketMode.value==='all'||row.market===marketMode.value).filter(row=>evidenceMode.value==='production'?row.eligible:true))
const selectedIds=computed(()=>new Set(selected.value.map(row=>row.id))),occupied=computed(()=>new Set(selected.value.map(row=>String(row.game.id))))
const joint=computed(()=>selected.value.reduce((product,row)=>product*row.probability,1)),average=computed(()=>selected.value.length?selected.value.reduce((sum,row)=>sum+row.probability,0)/selected.value.length:0)
const targetOptions=Array.from({length:9},(_,index)=>({value:index+2,label:`${index+2} legs`}))
const evidenceOptions=[{value:'shadow',label:'Shadow research',meta:'All forecasts'},{value:'production',label:'Production eligible',meta:'Audited only'}]
const competitionOptions=computed(()=>leagues.value.map(row=>({value:String(row.id),label:row.name,meta:row.code||row.discipline})))
const toggle=row=>{if(selectedIds.value.has(row.id)){selected.value=selected.value.filter(item=>item.id!==row.id);return}if(occupied.value.has(String(row.game.id))||selected.value.length>=Number(target.value))return;selected.value=[...selected.value,row]}
const buildBest=()=>{const rows=[],events=new Set(),directions=new Map(),directionCap=Math.max(2,Math.ceil(Number(target.value)/2));for(const row of candidates.value){const side=row.market.replace(/^(home|away|over|under).*/,'$1');if(events.has(String(row.game.id))||(directions.get(side)||0)>=directionCap)continue;rows.push(row);events.add(String(row.game.id));directions.set(side,(directions.get(side)||0)+1);if(rows.length>=Number(target.value))break}selected.value=rows}
const changeCompetition=value=>router.replace({query:{...route.query,competition:value,discipline:props.sport==='esports'?leagues.value.find(row=>String(row.id)===String(value))?.discipline:undefined}})
const load=async()=>{loading.value=true;error.value='';selected.value=[];try{const directory=await api.sportDirectory(props.sport,'leagues',{discipline:route.query.discipline});leagues.value=directory.items||[];const chosen=competition.value&&leagues.value.some(row=>String(row.id)===competition.value)?competition.value:String(leagues.value[0]?.id||'');if(chosen!==competition.value){changeCompetition(chosen);return}const result=await api.sportDirectory(props.sport,'games',{competition:chosen,discipline:league.value?.discipline||route.query.discipline,tournament:props.sport==='esports'?chosen:undefined});games.value=(result.items||[]).filter(game=>game.status!=='Completed')}catch(caught){error.value=caught?.message||'The competition builder could not be loaded.'}finally{loading.value=false}}
watch(()=>[props.sport,route.query.competition,route.query.discipline],load)
watch([evidenceMode,marketMode,target],()=>{selected.value=[]})
onMounted(load)
</script>

<template>
  <div class="unified-builder competition-builder" :style="{'--sport':active.accent}">
    <UnifiedBuilderHero :eyebrow="`${sportLabel(sport).toUpperCase()} / BUILDER`" :title="sport==='football'?'Build the match':'Build the series'" :accent="sport==='football'?'in context.':'from evidence.'" :description="sport==='football'?'Moneyline, draw, total-goals and both-teams-to-score distributions now use the same card-first hierarchy as MLB.':'Valorant, CS2 and League of Legends match-winner forecasts now use the same card-first hierarchy as MLB.'">
      <div class="builder-segment"><small>MODEL</small><div><button :class="{active:marketMode==='all'}" @click="marketMode='all'">ALL</button><button v-for="market in marketKeys.slice(0,5)" :key="market" :class="{active:marketMode===market}" @click="marketMode=market">{{sentenceCase(market).toUpperCase()}}</button></div></div>
      <div class="builder-control-bar"><CustomSelect :model-value="competition" label="Competition" :options="competitionOptions" searchable @update:model-value="changeCompetition"/><CustomSelect v-model="evidenceMode" label="Evidence" :options="evidenceOptions"/><CustomSelect v-model="target" label="Target legs" :options="targetOptions"/><button class="builder-refresh" :disabled="loading" @click="load"><RefreshCw :class="{spin:loading}"/> REFRESH</button></div>
    </UnifiedBuilderHero>
    <UnifiedBuilderScore :probability="joint" :selected="selected.length" :target="Number(target)" :average="average" :title="selected.length?`${selected.length}-leg ${league?.code||sportLabel(sport)} card`:'No legs selected'" description="The joint score multiplies exact-event model probabilities. One leg is permitted per match and Build Best caps repeated statistical directions." :detail="`${candidates.length} current signals from ${league?.name||'the selected competition'}. Research selections never become production legs by implication.`" fourth-label="EVIDENCE" :fourth-value="evidenceMode==='production'?'AUTO':'SHADOW'">
      <template #actions><button class="primary" :disabled="!candidates.length" @click="buildBest"><Sparkles/> BUILD BEST {{target}}</button><button :disabled="!selected.length" @click="selected=[]"><Trash2/> CLEAR</button></template>
    </UnifiedBuilderScore>
    <section class="builder-board-note"><span><i></i>{{games.length}} UPCOMING {{sport==='esports'?'SERIES':'FIXTURES'}} · {{candidates.length}} FORECAST OUTCOMES</span><p>Only forecasts exported for the exact event ID appear. Production mode filters the same board instead of changing the underlying probabilities.</p></section>
    <div v-if="selected.length" class="builder-selected-summary"><AnimatePresence mode="popLayout"><motion.article v-for="(row,index) in selected" :key="row.id" layout :initial="reduced?false:{opacity:0,y:10}" :animate="{opacity:1,y:0}" :exit="reduced?undefined:{opacity:0,scale:.97}"><span>{{String(index+1).padStart(2,'0')}}</span><div><small>{{sentenceCase(row.market)}} · {{probability(row.probability)}}</small><b>{{row.label}}</b><em>{{row.game.away?.name}} @ {{row.game.home?.name}}</em></div><button @click="toggle(row)">×</button></motion.article></AnimatePresence></div>
    <section class="builder-day"><header><div><span class="eyebrow">{{league?.name||'CURRENT COMPETITION'}}</span><h2>{{candidates.length}} source-backed outcomes</h2></div><small>{{games.length}} EVENTS</small></header>
      <div v-if="loading" class="builder-state"><RefreshCw class="spin"/><b>Loading competition evidence</b><p>Joining the exact fixture IDs to their latest immutable model export.</p></div>
      <div v-else-if="error" class="builder-state"><AlertTriangle/><b>Builder unavailable</b><p>{{error}}</p></div>
      <div v-else-if="!candidates.length" class="builder-state"><LockKeyhole/><b>No forecast export matches these controls</b><p>Fixtures remain visible elsewhere; this builder does not manufacture selections from standings.</p></div>
      <LayoutGroup v-else :id="`${sport}-builder`"><motion.div layout class="builder-card-grid"><AnimatePresence mode="popLayout"><motion.article v-for="row in candidates" :key="row.id" layout class="builder-choice-card" :class="{selected:selectedIds.has(row.id)}" :initial="reduced?false:{opacity:0,y:12}" :animate="{opacity:1,y:0}" :exit="reduced?undefined:{opacity:0,scale:.98}" :while-hover="reduced?undefined:{y:-2}">
        <div class="builder-card-meta"><span>{{row.game.date}} · {{row.game.time}}</span><strong>{{row.eligible?'AUTO ELIGIBLE':'SHADOW ONLY'}}</strong></div>
        <div class="builder-matchup"><div class="builder-team"><SportIdentity :identity="row.game.away" :size="38"/><span><small>{{sport==='esports'?'SIDE A':'AWAY'}}</small><b>{{row.game.away?.name}}</b></span></div><i class="builder-versus">{{sport==='esports'?'VS':'AT'}}</i><div class="builder-team home"><SportIdentity :identity="row.game.home" :size="38"/><span><small>{{sport==='esports'?'SIDE B':'HOME'}}</small><b>{{row.game.home?.name}}</b></span></div></div>
        <div class="builder-market-label">{{sentenceCase(row.market)}}<span>{{league?.code||sportLabel(sport)}}</span></div>
        <button class="builder-selection" :class="{active:selectedIds.has(row.id)}" :disabled="!selectedIds.has(row.id)&&(occupied.has(String(row.game.id))||selected.length>=Number(target))" @click="toggle(row)"><span><small>{{row.eligible?'AUDITED RELEASE':'RESEARCH OBSERVATION'}}</small><b>{{row.label}}</b></span><strong>{{probability(row.probability)}}</strong><Check v-if="selectedIds.has(row.id)"/><Plus v-else/></button>
        <footer class="builder-card-footer"><span>{{row.game.venue||row.game.competition}}</span><b>ONE PICK PER EVENT</b></footer>
      </motion.article></AnimatePresence></motion.div></LayoutGroup>
    </section>
  </div>
</template>

<style scoped>.competition-builder{padding-top:20px}.builder-control-bar{grid-template-columns:minmax(230px,1.5fr) minmax(170px,1fr) minmax(130px,.7fr) auto}.builder-control-bar :deep(.custom-select){min-width:0}@media(max-width:850px){.builder-control-bar{grid-template-columns:1fr 1fr}}@media(max-width:500px){.builder-control-bar{grid-template-columns:1fr}}</style>
