<script setup>
import TeamLogo from '../team/TeamLogo.vue'
import PlayerHeadshot from '../player/PlayerHeadshot.vue'

const { game, context } = defineProps({ game: { type: Object, required: true }, context: { type: Object, default: () => ({}) } })
const groups = side => [
  { key: 'lineup_players', label: 'Starting fielders / order', tone: 'lineup', empty: 'Starting lineup has not been submitted.' },
  { key: 'bullpen_players', label: 'Bullpen', tone: 'bullpen', empty: 'Bullpen personnel have not been submitted.' },
].map(group => ({ ...group, players: context?.[side]?.[group.key] || [] }))
</script>

<template>
  <section class="personnel panel">
    <header class="personnel-title"><div><span class="eyebrow">OFFICIAL MLB PERSONNEL</span><h2>Who can shape this matchup.</h2></div><p>Starting order and submitted bullpen arms from the live boxscore.</p></header>
    <div class="team-columns">
      <article v-for="side in ['away','home']" :key="side" class="team-personnel">
        <header><TeamLogo :team="game[side]" :size="48"/><div><small>{{ side.toUpperCase() }} TEAM</small><h3>{{ game[side].name }}</h3></div><span class="roster-state" :class="context?.[side]?.lineup_confirmed ? 'confirmed' : 'pending'">{{ context?.[side]?.lineup_confirmed ? 'LINEUP CONFIRMED' : 'LINEUP PENDING' }}</span></header>
        <section v-for="group in groups(side)" :key="group.key" class="person-group" :class="group.tone">
          <div class="group-title"><span><i></i>{{ group.label }}</span><b>{{ group.players.length }}</b></div>
          <div v-if="group.players.length" class="person-grid">
            <RouterLink v-for="player in group.players" :key="`${group.key}-${player.id}`" :to="`/players/${player.id}`" class="person-card">
              <PlayerHeadshot :id="player.id" :name="player.name" :size="48"/>
              <span><small>{{ player.batting_order ? `#${player.batting_order} · ` : '' }}{{ player.position }}</small><b>{{ player.name }}</b></span>
            </RouterLink>
          </div>
          <p v-else>{{ group.empty }}</p>
        </section>
      </article>
    </div>
  </section>
</template>

<style scoped>
.personnel{overflow:hidden}.personnel-title{display:flex;align-items:end;justify-content:space-between;gap:24px;padding:20px;border-bottom:1px solid var(--line)}.personnel-title h2{font-size:21px;margin:7px 0 0}.personnel-title p{max-width:500px;margin:0;text-align:right;font-size:9px;color:var(--muted);line-height:1.55}.team-columns{display:grid;grid-template-columns:1fr 1fr}.team-personnel{min-width:0;padding:16px 18px 20px}.team-personnel+article{border-left:1px solid var(--line)}.team-personnel>header{display:flex;align-items:center;gap:10px;padding-bottom:13px;border-bottom:1px solid var(--line)}.team-personnel>header>div{min-width:0}.team-personnel>header small{font:500 7px 'DM Mono';color:var(--muted)}.team-personnel h3{font-size:14px;margin:4px 0 0}.roster-state{margin-left:auto;padding:5px 7px;border:1px solid var(--line);font:600 6px 'DM Mono';letter-spacing:.07em}.roster-state.confirmed{border-color:color-mix(in srgb,var(--acid) 60%,var(--line));color:var(--acid)}.roster-state.pending{color:var(--orange)}.person-group{--role:var(--acid);margin-top:17px}.person-group.bullpen{--role:var(--blue)}.group-title{display:flex;align-items:center;justify-content:space-between;padding-bottom:7px;border-bottom:1px solid var(--line)}.group-title span{display:flex;align-items:center;gap:7px;font:600 7px 'DM Mono';letter-spacing:.07em;text-transform:uppercase}.group-title i{width:7px;height:7px;background:var(--role)}.group-title b{color:var(--role);font:600 9px 'DM Mono'}.person-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-top:7px}.person-card{min-width:0;display:flex;align-items:center;gap:8px;padding:6px;background:var(--wash);border-left:2px solid var(--role)}.person-card :deep(.headshot){flex:none;border:0;border-radius:0;background:var(--surface)}.person-card>span{min-width:0;display:flex;flex-direction:column}.person-card small{font:600 6px 'DM Mono';color:var(--role)}.person-card b{margin-top:4px;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.person-group>p{margin:8px 0 0;padding:12px;background:var(--wash);font-size:8px;color:var(--muted)}@media(max-width:1080px){.person-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.personnel-title{align-items:flex-start;flex-direction:column}.personnel-title p{text-align:left}.team-columns{grid-template-columns:1fr}.team-personnel+article{border-left:0;border-top:1px solid var(--line)}}@media(max-width:430px){.person-grid{grid-template-columns:1fr}.roster-state{display:none}}
</style>
<style scoped>.person-card{color:var(--text);text-decoration:none}.person-card:hover b{text-decoration:underline;text-decoration-color:var(--role)}</style>
