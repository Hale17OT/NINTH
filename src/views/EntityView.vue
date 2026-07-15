<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../services/api'
import ContextBack from '../components/navigation/ContextBack.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import LoadError from '../components/ui/LoadError.vue'
import MetricCard from '../components/ui/MetricCard.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import TrendChart from '../components/charts/TrendChart.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import PlayerHeadshot from '../components/player/PlayerHeadshot.vue'

const props = defineProps({ type: String })
const route = useRoute()
const data = ref()
const loading = ref(true)
const error = ref('')
let loadToken = 0
const rosterGroups = ['Starting rotation', 'Bullpen', 'Starting lineup', 'Bench']
const groupedRoster = computed(() => Object.fromEntries(rosterGroups.map(group => [group, (data.value?.roster || []).filter(player => player.group === group)])))
const load = async () => {
  const token = ++loadToken
  loading.value = true
  error.value = ''
  try {
    const result = props.type === 'team' ? await api.team(route.params.id) : await api.player(route.params.id)
    if (token === loadToken) data.value = result
  } catch (caught) {
    if (token === loadToken) { data.value = undefined; error.value = caught?.message || 'This profile could not be loaded.' }
  } finally {
    if (token === loadToken) loading.value = false
  }
}
onMounted(load)
watch(() => route.params.id, load)
</script>

<template>
  <div v-if="data" class="entity">
    <ContextBack :fallback="type === 'team' ? '/teams' : '/players'"/>
    <section class="profile">
      <div class="identity"><TeamLogo v-if="type==='team'" :team="{id:data.teamId,abbr:data.abbr,name:data.name}" :size="122"/><PlayerHeadshot v-else :id="data.playerId" :name="data.name" :size="126"/><div><span class="eyebrow">{{ data.kicker }}</span><h1>{{ data.name }}</h1><p>{{ data.subtitle }}</p></div></div>
      <div class="profile-side"><small>{{ data.highlightLabel }}</small><b class="mono">{{ data.highlight }}</b></div>
    </section>
    <div class="grid-auto"><MetricCard v-for="metric in data.metrics" :key="metric.label" v-bind="metric"/></div>
    <div class="entity-grid"><SectionCard :title="data.chartTitle"><TrendChart :values="data.chart" :labels="data.chartLabels" :type="data.chartType" :unit="data.chartUnit"/><div class="note"><b>SOURCE NOTE</b>{{ data.insight }}</div></SectionCard><SectionCard :title="data.rankingTitle"><div v-for="item in data.ranks" :key="item.label" class="rank"><div><b>{{ item.label }}</b><strong class="mono">{{ item.value }}</strong></div><div class="progress"><i :style="{width:`${item.score}%`}"></i></div><small>{{ item.note }}</small></div></SectionCard></div>

    <template v-if="type === 'team'">
      <SectionCard title="Complete active roster" subtitle="Roles are grouped from official active-roster positions and current-season usage">
        <div class="roster-groups">
          <section v-for="group in rosterGroups" :key="group" v-show="groupedRoster[group]?.length" class="roster-group">
            <header><span class="eyebrow">{{ group }}</span><b class="mono">{{ groupedRoster[group]?.length }}</b></header>
            <div class="roster-grid">
              <RouterLink v-for="player in groupedRoster[group]" :key="player.id" :to="{path:`/players/${player.id}`,query:{from:`/teams/${data.teamId}`}}" class="roster-card" :class="`role-${group.toLowerCase().replaceAll(' ','-')}`">
                <PlayerHeadshot :id="player.id" :name="player.name" :size="112"/>
                <div><span class="role">{{ player.role }}</span><h3>{{ player.name }}</h3><p>#{{ player.number }} · {{ player.positionName }}</p><small v-if="player.starts">{{ player.starts }} starts · {{ player.innings || '—' }} IP</small><small v-else>{{ player.games }} games<span v-if="player.ops"> · {{ player.ops }} OPS</span></small></div>
              </RouterLink>
            </div>
          </section>
        </div>
      </SectionCard>
      <SectionCard :title="data.statusTitle"><div v-for="item in data.status" :key="item.name" class="status"><div><b>{{ item.name }}</b><small>{{ item.detail }}</small></div><strong class="mono" :class="item.tone">{{ item.value }}</strong></div></SectionCard>
    </template>

    <div v-else class="entity-grid"><SectionCard :title="data.leaderTitle"><div class="leaders"><article v-for="person in data.leaders" :key="person.name"><PlayerHeadshot class="portrait" :id="person.id" :name="person.name" :size="140"/><h3>{{ person.name }}</h3><p>{{ person.role }}</p><div><span v-for="(value,key) in person.stats" :key="key"><small>{{ key }}</small><b class="mono">{{ value }}</b></span></div></article></div></SectionCard><SectionCard :title="data.statusTitle"><div v-for="item in data.status" :key="item.name" class="status"><div><b>{{ item.name }}</b><small>{{ item.detail }}</small></div><strong class="mono" :class="item.tone">{{ item.value }}</strong></div></SectionCard></div>
    <SectionCard :title="data.tableTitle"><div class="table-wrap"><table class="data-table"><thead><tr><th v-for="heading in data.table.headers" :key="heading">{{ heading }}</th></tr></thead><tbody><tr v-for="(row,index) in data.table.rows" :key="index"><td v-for="(value,cell) in row" :key="cell" :class="cell?'mono':''">{{ value }}</td></tr></tbody></table></div></SectionCard>
  </div>
  <LoadError v-else-if="error" :message="error" @retry="load"/>
  <LoadingState v-else-if="loading" :label="type === 'team' ? 'Loading team room' : 'Loading player profile'" detail="Synchronizing the latest official roster and season statistics."/>
</template>

<style scoped>
.entity{display:grid;gap:11px;padding-top:20px}.back{display:flex;align-items:center;gap:6px;width:max-content;padding:8px 0;text-decoration:none;font:600 8px 'DM Mono';color:var(--muted)}.profile{min-height:260px;padding:32px 0;display:flex;align-items:center;gap:30px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.identity{display:flex;align-items:center;gap:24px}.identity>div{min-width:0}h1{font-size:clamp(38px,6vw,78px);line-height:.9;letter-spacing:-.075em;margin:13px 0 18px}.profile p{font:9px 'DM Mono';color:var(--muted)}.profile-side{margin-left:auto;min-width:180px;height:150px;background:var(--ink);color:var(--paper);display:flex;flex-direction:column;justify-content:end;padding:20px}.profile-side small{font:500 8px 'DM Mono';color:#989d95}.profile-side b{font-size:36px;color:var(--accent);margin-top:8px}.entity-grid{display:grid;grid-template-columns:1.45fr 1fr;gap:11px}.note{border-left:3px solid var(--orange);padding:12px;margin-top:10px;font-size:10px;line-height:1.6;color:var(--muted)}.note b{display:block;font:600 7px 'DM Mono';color:var(--text);margin-bottom:5px}.rank{margin:17px 0}.rank>div{display:flex;justify-content:space-between;font-size:10px;margin-bottom:7px}.rank small{display:block;color:var(--muted);font:8px 'DM Mono';margin-top:6px}.leaders{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.leaders article{padding:12px;background:var(--wash);min-width:0}.portrait{height:140px;width:100%!important;background:var(--surface)}.leaders h3{margin:10px 0 2px;font-size:12px}.leaders p{font-size:8px;color:var(--muted);margin:0 0 10px}.leaders article>div:last-child{display:flex;gap:20px}.leaders span{display:flex;flex-direction:column}.leaders small{font-size:7px;color:var(--muted)}.leaders b{font-size:10px}.status{display:flex;align-items:center;gap:10px;border-top:1px solid var(--line);padding:13px 0}.status div{display:flex;flex-direction:column}.status small{font-size:8px;color:var(--muted);margin-top:3px}.status strong{margin-left:auto;font-size:11px}.roster-groups{display:grid;gap:28px}.roster-group>header{display:flex;align-items:center;justify-content:space-between;padding-bottom:9px;border-bottom:1px solid var(--ink)}.roster-group>header b{font-size:9px;color:var(--muted)}.roster-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}.roster-card{min-width:0;display:grid;grid-template-columns:112px 1fr;align-items:stretch;border:1px solid var(--line);background:var(--wash);text-decoration:none;overflow:hidden}.roster-card :deep(.headshot){border:0;border-right:1px solid var(--line);border-radius:0;width:112px!important;height:132px!important}.roster-card>div{min-width:0;padding:12px;display:flex;flex-direction:column}.roster-card .role{width:max-content;max-width:100%;padding:4px 6px;background:var(--ink);color:var(--accent);font:600 7px 'DM Mono';text-transform:uppercase}.roster-card h3{font-size:12px;margin:10px 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.roster-card p,.roster-card small{font-size:8px;color:var(--muted);margin:0}.roster-card small{margin-top:auto}.state{padding:90px;text-align:center;font:9px 'DM Mono'}
.roster-card{border-left:4px solid var(--role-color,#777)}.roster-card .role{background:var(--role-color,#777);color:#fff}.role-starting-rotation{--role-color:#d95436}.role-bullpen{--role-color:#276b9a}.role-starting-lineup{--role-color:#568900}.role-bench{--role-color:#686c66}.roster-group:nth-child(1)>header{border-color:#d95436}.roster-group:nth-child(2)>header{border-color:#276b9a}.roster-group:nth-child(3)>header{border-color:#568900}.roster-group:nth-child(4)>header{border-color:#686c66}
@media(max-width:1100px){.roster-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:800px){.profile{align-items:flex-start;flex-wrap:wrap}.identity{align-items:flex-start}.profile-side{width:100%;height:110px;margin:0}.entity-grid{grid-template-columns:1fr}.leaders{grid-template-columns:1fr 1fr}}@media(max-width:600px){.roster-grid{grid-template-columns:1fr}.roster-card{grid-template-columns:96px 1fr}.roster-card :deep(.headshot){width:96px!important;height:118px!important}}@media(max-width:520px){.identity{flex-direction:column}.leaders{grid-template-columns:1fr}.profile{padding:22px 0}}
</style>
