<script setup>
import TeamLogo from '../team/TeamLogo.vue'

defineProps({ game: Object, live: Boolean })
</script>

<template>
  <article class="game-card">
    <header>
      <span v-if="live" class="live"><i class="live-dot"></i> LIVE / {{ game.inning }}</span>
      <span v-else>{{ game.time }} / {{ game.stadium }}</span>
      <b>{{ game.status }}</b>
    </header>
    <div class="team-row">
      <TeamLogo :team="game.away" :size="42"/>
      <div><b>{{ game.away.name }}</b><small>{{ game.away.abbr }} / AWAY</small></div>
      <strong v-if="live" class="mono">{{ game.away.score }}</strong>
    </div>
    <div class="team-row">
      <TeamLogo :team="game.home" :size="42"/>
      <div><b>{{ game.home.name }}</b><small>{{ game.home.abbr }} / HOME</small></div>
      <strong v-if="live" class="mono">{{ game.home.score }}</strong>
    </div>
    <div v-if="!live" class="context">
      <span><small>STARTERS</small>{{ game.pitchers[0] }} / {{ game.pitchers[1] }}</span>
      <span><small>WEATHER</small>{{ game.weather || 'Pending' }}</span>
    </div>
    <footer>
      <span>{{ live ? 'Official live game feed' : game.insight }}</span>
      <RouterLink :to="live ? `/live/${game.id}` : `/games/${game.id}`">{{ live ? 'FOLLOW LIVE' : 'OPEN ANALYSIS' }} ↗</RouterLink>
    </footer>
  </article>
</template>

<style scoped>
.game-card { min-height: 360px; padding: 22px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); transition: transform .25s var(--ease-emphasized),border-color .25s; }
.game-card:hover { border-color: var(--accent); transform: translateY(-4px); }
header { display: flex; justify-content: space-between; gap: 10px; padding-bottom: 14px; border-bottom: 1px solid var(--line); color: var(--muted); font: 500 12px 'DM Mono'; }
header b { color: var(--text); }
.live { display: flex; align-items: center; gap: 8px; color: var(--red); }
.team-row { display: grid; grid-template-columns: 46px 1fr auto; gap: 12px; align-items: center; padding: 15px 0; border-bottom: 1px solid var(--line); }
.team-row > div { display: flex; min-width: 0; flex-direction: column; }
.team-row > div b { overflow: hidden; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.team-row small { margin-top: 4px; color: var(--muted); font: 500 12px 'DM Mono'; }
.team-row strong { font-size: 28px; letter-spacing: -.08em; }
.context { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 16px 0; }
.context span { font-size: 13px; line-height: 1.5; }
.context small { display: block; margin-bottom: 5px; color: var(--muted); font: 600 12px 'DM Mono'; }
footer { display: flex; justify-content: space-between; gap: 14px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }
footer a { color: var(--accent); font: 700 12px 'DM Mono'; text-decoration: none; white-space: nowrap; }
@media (max-width:430px) { .game-card { min-height: 330px; padding: 18px; } .context { grid-template-columns: 1fr; } .context span:last-child { display: none; } footer { align-items: flex-start; flex-direction: column; } }
</style>
