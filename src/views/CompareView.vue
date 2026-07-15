<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../services/api'
import SectionCard from '../components/ui/SectionCard.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import CustomSelect from '../components/ui/CustomSelect.vue'
const teams=ref([]),left=ref(147),right=ref(119)
onMounted(async()=>{teams.value=await api.teams()})
const leftTeam=computed(()=>teams.value.find(team=>team.id===Number(left.value))||{})
const rightTeam=computed(()=>teams.value.find(team=>team.id===Number(right.value))||{})
const teamOptions=computed(()=>teams.value.map(team=>({value:team.id,label:team.name,meta:team.abbr})))
const rate=(team,key)=>team?.[key]?.wins!=null?`${team[key].wins}-${team[key].losses}`:'—'
const rows=computed(()=>[
  {label:'Overall record',left:`${leftTeam.value.wins||0}-${leftTeam.value.losses||0}`,right:`${rightTeam.value.wins||0}-${rightTeam.value.losses||0}`},
  {label:'Winning percentage',left:leftTeam.value.pct||'—',right:rightTeam.value.pct||'—'},
  {label:'Runs scored',left:leftTeam.value.runs_scored??'—',right:rightTeam.value.runs_scored??'—'},
  {label:'Runs allowed',left:leftTeam.value.runs_allowed??'—',right:rightTeam.value.runs_allowed??'—'},
  {label:'Run differential',left:leftTeam.value.run_differential??'—',right:rightTeam.value.run_differential??'—'},
  {label:'Home record',left:rate(leftTeam.value,'home'),right:rate(rightTeam.value,'home')},
  {label:'Away record',left:rate(leftTeam.value,'away'),right:rate(rightTeam.value,'away')},
  {label:'Last 10',left:rate(leftTeam.value,'last_ten'),right:rate(rightTeam.value,'last_ten')},
  {label:'Current streak',left:leftTeam.value.streak||'—',right:rightTeam.value.streak||'—'},
])
</script>
<template><div class="compare"><section class="head panel"><span class="eyebrow">OFFICIAL TEAM COMPARISON</span><h1>Side-by-side MLB records</h1><p>Every value below comes from the current MLB standings feed.</p></section><div class="selectors"><CustomSelect v-model="left" :options="teamOptions" searchable/><b>VS</b><CustomSelect v-model="right" :options="teamOptions" searchable/></div><div class="team-head panel"><div><TeamLogo :team="leftTeam" :size="76"/><span><b class="mono">{{leftTeam.abbr}}</b><small>{{leftTeam.name}}</small></span></div><strong>MLB 2026</strong><div><span><b class="mono">{{rightTeam.abbr}}</b><small>{{rightTeam.name}}</small></span><TeamLogo :team="rightTeam" :size="76"/></div></div><SectionCard title="Official season comparison" subtitle="Standings, scoring, splits, and current form"><div class="comparison-table"><div class="compare-row header"><b>{{leftTeam.abbr}}</b><span>Category</span><b>{{rightTeam.abbr}}</b></div><div v-for="row in rows" :key="row.label" class="compare-row"><strong class="mono teal">{{row.left}}</strong><span>{{row.label}}</span><strong class="mono pink">{{row.right}}</strong></div></div></SectionCard><SectionCard title="Data notice"><p class="notice">Advanced radar scores, betting trends, and AI matchup claims were removed because no real provider currently supplies them. They will return only when backed by an auditable data pipeline.</p></SectionCard></div></template>
<style scoped>
.compare{display:grid;gap:14px}.head{padding:24px}h1{font-size:31px;margin:7px 0}.head p,.notice{font-size:12px;color:var(--muted);line-height:1.7}.selectors{display:grid;grid-template-columns:1fr auto 1fr;gap:15px;align-items:center}.selectors select{padding:12px;background:var(--raised);border:1px solid var(--line);color:var(--text);border-radius:6px}.team-head{display:grid;grid-template-columns:1fr auto 1fr;padding:20px;align-items:center}.team-head>div{display:flex;align-items:center;gap:14px}.team-head>div:last-child{text-align:right;justify-content:flex-end}.team-head>div>span{display:flex;flex-direction:column}.team-head b{font-size:25px;color:var(--acid)}.team-head small,.team-head>strong{font-size:9px;color:var(--muted)}.comparison-table{display:grid}.compare-row{display:grid;grid-template-columns:1fr 1.4fr 1fr;align-items:center;text-align:center;padding:12px;border-top:1px solid var(--line);font-size:11px}.compare-row>strong:first-child{text-align:left}.compare-row>strong:last-child{text-align:right}.compare-row.header{border:0;background:var(--raised);font-size:10px}.compare-row.header b:first-child{text-align:left}.compare-row.header b:last-child{text-align:right}@media(max-width:650px){.team-head{grid-template-columns:1fr 1fr}.team-head>strong{display:none}.team-head>div{flex-direction:column}.team-head>div:last-child{flex-direction:column-reverse}.compare-row{grid-template-columns:.8fr 1.4fr .8fr;padding:10px 5px}}
</style>
