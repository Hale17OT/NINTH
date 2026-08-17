<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeft, Activity, Database, ShieldCheck, TrendingUp } from 'lucide-vue-next'
import { motion, useReducedMotion } from 'motion-v'
import { useRoute } from 'vue-router'
import SportIdentity from '../components/identity/SportIdentity.vue'
import SportCrumbs from '../components/navigation/SportCrumbs.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import LoadError from '../components/ui/LoadError.vue'
import PlayerPercentileProfile from '../components/analytics/PlayerPercentileProfile.vue'
import RollingTrend from '../components/analytics/RollingTrend.vue'
import SplitComparison from '../components/analytics/SplitComparison.vue'
import AdvancedMetricTable from '../components/analytics/AdvancedMetricTable.vue'
import ModelDriverPanel from '../components/analytics/ModelDriverPanel.vue'
import { entityRoute, metricValue, sentenceCase, sportLabel } from '../domain/sports'
import { sportById } from '../config/sports'
import { api } from '../services/api'

const props=defineProps({sport:{type:String,required:true}}),route=useRoute(),payload=ref(null),loading=ref(true),error=ref(''),imageFailed=ref(false)
const reduced=useReducedMotion()
const active=computed(()=>sportById(props.sport)),player=computed(()=>payload.value?.identity||{}),analytics=computed(()=>payload.value?.analytics||{})
const rawStats=computed(()=>Object.entries(player.value.statistics||{}))
const profileMetrics=computed(()=>analytics.value.metrics||rawStats.value.map(([key,value])=>({key,label:sentenceCase(key),value,definition:'Current source-backed provider field.'})))
const trends=computed(()=>analytics.value.trends||{})
const trendSeries=computed(()=>{
  const rows=[]
  if (trends.value.primary?.length) rows.push({label:sentenceCase(trends.value.primaryLabel||'Primary output'),values:trends.value.primary,color:active.value.accent})
  if (trends.value.secondary?.length) rows.push({label:sentenceCase(trends.value.secondaryLabel||'Secondary output'),values:trends.value.secondary,color:'#809fff',fill:false})
  return rows
})
const drivers=computed(()=>[...profileMetrics.value].filter(row=>row.percentile!=null).sort((a,b)=>b.percentile-a.percentile).slice(0,3).map(row=>({label:row.label,detail:`${row.percentile}th percentile · ${metricValue(row.value,2)}`})))
const roleContext=computed(()=>{
  if(props.sport==='american-football') return `${player.value.position||'Position'} metrics are kept separate: a quarterback is evaluated with passing volume and EPA, a receiver with targets and receiving efficiency, and a runner with touches and scrimmage production.`
  if(props.sport==='basketball') return 'Per-game production is paired with clearly labeled per-36 derivatives. Tracking, usage and on/off values stay absent until a permitted source supplies them.'
  if(props.sport==='football') return 'Goals, assists and expected production are normalized per 90 minutes for positional comparison. Raw season minutes remain visible so small samples are not hidden.'
  return 'Game-native source fields remain separate from cross-game presentation metrics.'
})
const load=async()=>{loading.value=true;error.value='';imageFailed.value=false;try{payload.value=await api.sportWorkspace(props.sport,'player',route.params.id,{team:route.query.team,competition:route.query.competition,discipline:route.query.discipline})}catch(caught){error.value=caught?.message||'The player workspace could not be loaded.'}finally{loading.value=false}}
watch(()=>[props.sport,route.params.id,route.query.team],load);onMounted(load)
</script>

<template><div class="player-view" :style="{'--sport':active.accent}"><LoadingState v-if="loading" label="Opening player intelligence" detail="Resolving identity, role peers, current statistics and chronological evidence."/><LoadError v-else-if="error" :message="error" @retry="load"/><template v-else>
  <SportCrumbs :items="[{label:sportLabel(sport),to:active.route},{label:payload.league?.name||player.competition,to:payload.league?entityRoute(sport,'leagues',payload.league):`${active.route}/leagues`},{label:payload.team?.name||player.team,to:payload.team?entityRoute(sport,'teams',payload.team,{competition:payload.team.competitionId}):null},{label:player.name}]"/>
  <section class="player-hero">
    <motion.div class="portrait" :initial="reduced?false:{opacity:0,x:-24,scale:.96}" :animate="{opacity:1,x:0,scale:1}" :transition="{type:'spring',stiffness:145,damping:22}"><img v-if="player.image&&!imageFailed" :src="player.image" :alt="player.name" @error="imageFailed=true"><SportIdentity v-else :identity="player" :size="180" square/></motion.div>
    <motion.div class="copy" :initial="reduced?false:{opacity:0,y:20}" :animate="{opacity:1,y:0}" :transition="{duration:.55,delay:.08}"><span class="eyebrow">{{player.position||'Player'}} · {{player.team||player.competition}}</span><h1>{{player.name}}<i>.</i></h1><p><template v-if="player.number">#{{player.number}} · </template>{{player.nationality||'Nationality unavailable'}}<template v-if="player.height"> · {{player.height}}</template><template v-if="player.weight"> · {{player.weight}}</template></p><RouterLink v-if="payload.team" :to="entityRoute(sport,'teams',payload.team,{competition:payload.team.competitionId})"><ArrowLeft/> {{payload.team.name}} ROSTER</RouterLink></motion.div>
    <motion.aside :initial="reduced?false:{opacity:0,x:24}" :animate="{opacity:1,x:0}" :transition="{duration:.55,delay:.14}"><Activity/><span>PLAYER INTELLIGENCE</span><b>{{analytics.peerSample?`${analytics.peerSample} role peers`:'Identity verified'}}</b><p>{{rawStats.length?`${rawStats.length} source-backed season fields · ${analytics.season||'current'} sample`:'The provider returned a verified player identity but no universal performance record. NINTH does not manufacture one.'}}</p><small>{{analytics.source}}</small></motion.aside>
  </section>

  <section class="stat-grid" v-if="rawStats.length"><motion.article v-for="([key,value],index) in rawStats.slice(0,10)" :key="key" :initial="reduced?false:{opacity:0,y:12}" :animate="{opacity:1,y:0}" :transition="{duration:.32,delay:Math.min(index*.035,.28)}"><small>{{String(index+1).padStart(2,'0')}}</small><b>{{metricValue(value,Number(value)<2?2:1)}}</b><span>{{sentenceCase(key)}}</span></motion.article></section>

  <ModelDriverPanel :text="analytics.interpretation||roleContext" :drivers="drivers"/>

  <section v-if="trendSeries.length" class="trend-layout"><RollingTrend :labels="trends.labels" :series="trendSeries" :title="`${player.position||'Player'} game-by-game output`" :height="345"><p class="chart-note">Weekly/game values are chronological source observations. They are descriptive and are not reconstructed from season totals.</p></RollingTrend><SplitComparison :rows="analytics.splits||[]" title="Recent output versus season"/></section>

  <PlayerPercentileProfile :metrics="profileMetrics" :sample="analytics.peerSample||0" :title="`${player.position||'Role'} peer profile`"/>
  <AdvancedMetricTable :metrics="profileMetrics" :source="analytics.source" :title="`${player.position||'Player'} metric dictionary`"/>

  <section class="evidence"><header><div><span class="eyebrow">EVIDENCE CONTRACT</span><h2>What this profile can support</h2></div><Database/></header><div><article><ShieldCheck/><b>Verified identity</b><p>The route resolves through team and competition context, preserving a canonical roster identity.</p></article><article><TrendingUp/><b>Position-aware evidence</b><p>{{roleContext}}</p></article><article><Database/><b>Honest gaps</b><p>Unavailable injuries, tracking, splits or advanced fields remain explicitly absent rather than appearing as zeros.</p></article></div></section>
</template></div></template>

<style scoped>
.player-view{padding:18px 0 70px;display:grid;gap:16px}.player-hero{min-height:510px;display:grid;grid-template-columns:280px minmax(0,1fr) 310px;gap:45px;align-items:center;border-bottom:1px solid var(--line)}.portrait{height:390px;display:grid;place-items:center;overflow:hidden;border:1px solid var(--line);background:linear-gradient(155deg,color-mix(in srgb,var(--sport) 11%,var(--surface)),var(--raised))}.portrait img{width:100%;height:100%;object-fit:contain;object-position:center bottom}.copy h1{margin:14px 0;font-size:clamp(52px,7vw,105px);line-height:.83;letter-spacing:-.085em}.copy h1 i{font-style:normal;color:var(--sport)}.copy p{color:var(--muted);font-size:11px}.copy>a{width:max-content;display:flex;align-items:center;gap:7px;margin-top:25px;padding:11px 13px;background:var(--contrast);color:var(--on-contrast);font:700 8px 'DM Mono';text-decoration:none}.copy>a svg{width:14px;color:var(--sport)}.player-hero aside{min-height:290px;padding:23px;display:flex;flex-direction:column;background:var(--contrast);color:var(--on-contrast);border-top:4px solid var(--sport)}.player-hero aside>svg{color:var(--sport)}.player-hero aside span{margin-top:auto;font:700 7px 'DM Mono';color:var(--sport)}.player-hero aside b{margin:8px 0;font-size:25px}.player-hero aside p{color:#aeb5ab;font-size:9px;line-height:1.6}.player-hero aside small{font:600 6px/1.5 'DM Mono';color:#7f887d}.stat-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}.stat-grid article{min-height:145px;padding:15px;display:flex;flex-direction:column;background:var(--surface)}.stat-grid small{font:700 7px 'DM Mono';color:var(--sport)}.stat-grid b{margin:auto 0 5px;font:800 29px 'DM Mono'}.stat-grid span{font-size:9px;color:var(--muted)}.trend-layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(280px,.65fr);gap:16px}.chart-note{margin:10px 0 0;color:var(--muted);font-size:8px;line-height:1.5}.evidence{border:1px solid var(--line);background:var(--surface)}.evidence>header{min-height:90px;padding:18px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.evidence h2{margin:5px 0 0;font-size:28px}.evidence>header svg{color:var(--sport)}.evidence>div{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line)}.evidence article{min-height:200px;padding:22px;display:flex;flex-direction:column;background:var(--surface)}.evidence article svg{color:var(--sport)}.evidence article b{margin-top:auto;font-size:15px}.evidence article p{margin:8px 0 0;color:var(--muted);font-size:9px;line-height:1.6}@media(max-width:1100px){.player-hero{grid-template-columns:230px 1fr}.player-hero aside{grid-column:1/-1;min-height:220px}.portrait{height:320px}.trend-layout{grid-template-columns:1fr}.stat-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){.player-hero{grid-template-columns:1fr;padding:35px 0;gap:25px}.portrait{height:330px}.stat-grid{grid-template-columns:repeat(2,1fr)}.evidence>div{grid-template-columns:1fr}.copy h1{font-size:54px}.player-hero aside{grid-column:auto}}
</style>
