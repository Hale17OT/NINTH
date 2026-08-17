<script setup>
import { computed } from 'vue'
import { motion } from 'motion-v'
import { ArrowUpRight, BrainCircuit, RefreshCw } from 'lucide-vue-next'
import { useAppStore } from '../stores/app'
import GameCard from '../components/game/GameCard.vue'
import TeamLogo from '../components/team/TeamLogo.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SportVisual from '../components/ui/SportVisual.vue'
import BorderTrail from '../components/motion/BorderTrail.vue'

const store = useAppStore()
const data = computed(() => store.dashboard)
const featured = computed(() => data.value?.featured)
const dateLabel = computed(() => new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'America/New_York' }).format(new Date(featured.value?.gameTime || Date.now())))
const percent = value => value == null ? 'Pending' : `${(Number(value) * 100).toFixed(1)}%`
</script>

<template>
  <div v-if="data" class="home">
    <section class="hero">
      <div class="hero-beam" aria-hidden="true"></div>
      <div class="hero-main">
        <span class="eyebrow">{{dateLabel}} / THE DAILY READ</span>
        <h1>Baseball,<br><i>before first pitch.</i></h1>
        <p>One place for the games, people, form, and live circumstances that shape every matchup.</p>
        <div class="actions"><RouterLink to="/schedule">Open today’s games <ArrowUpRight/></RouterLink><button @click="store.load(true)"><RefreshCw/>{{store.loading?'Syncing':'Refresh'}}</button></div>
      </div>

      <motion.div class="hero-object" :initial="{opacity:0,scale:.86,rotate:-8}" :animate="{opacity:1,scale:1,rotate:0}" :transition="{type:'spring',stiffness:120,damping:19}"><SportVisual sport="baseball" accent="#d6ff61" compact/></motion.div>

      <div class="daily-card">
        <BorderTrail/>
        <header><span><BrainCircuit/> MODEL BRIEF</span><small>TOP MATCHUP / LIVE + NEXT 7 DAYS</small></header>
        <template v-if="featured">
          <div class="brief-match">
            <div><TeamLogo :team="featured.away" :size="58"/><b>{{featured.away.abbr}}</b><small>{{featured.away.record||'—'}}</small></div>
            <span><small>{{featured.status}}</small><strong class="mono">{{featured.time}}</strong><em>{{featured.stadium}}</em></span>
            <div><TeamLogo :team="featured.home" :size="58"/><b>{{featured.home.abbr}}</b><small>{{featured.home.record||'—'}}</small></div>
          </div>
          <div class="brief-signals"><span><small>MATCHUP QUALITY</small><b>{{featured.brief?.combinedStandingLabel||'Pending'}}</b></span><span><small>MODEL LEAN</small><b>{{featured.brief?.modelTeam?.abbr||'Pending'}}<template v-if="featured.brief?.modelProbability"> · {{percent(featured.brief.modelProbability)}}</template></b></span></div>
          <RouterLink :to="`/games/${featured.id}`">Read the matchup <ArrowUpRight/></RouterLink>
        </template>
        <div v-else class="brief-empty"><span>NO UPCOMING MATCHUP</span><p>No live or scheduled MLB game was found in the next seven days.</p></div>
      </div>
    </section>

    <section class="pulse"><div v-for="metric in data.metrics" :key="metric.label"><span>{{metric.label}}</span><strong class="mono">{{metric.value}}</strong><small>{{metric.delta}}</small></div></section>

    <section class="split">
      <div class="games">
        <header class="section-head"><div><span class="eyebrow">THE BOARD</span><h2>Today’s games</h2></div><RouterLink to="/schedule">Full schedule <ArrowUpRight/></RouterLink></header>
        <div v-if="data.live.length" class="game-list"><GameCard v-for="game in data.live" :key="game.id" :game="game" live/></div>
        <div v-if="data.today.length" class="game-list"><GameCard v-for="game in data.today.slice(0,4)" :key="game.id" :game="game"/></div>
        <EmptyState v-if="!data.live.length&&!data.today.length" kind="games" eyebrow="TODAY’S SLATE" title="No MLB games today" detail="The official schedule returned no live or upcoming games for today. The model brief above looks ahead for the next strongest matchup." action-label="Browse the schedule" action-to="/schedule"/>
      </div>
      <aside>
        <header class="section-head"><div><span class="eyebrow">TABLE</span><h2>Best records</h2></div></header>
        <template v-if="data.standings.length"><RouterLink v-for="(team,index) in data.standings" :key="team.id" :to="`/teams/${team.id}`" class="standing"><span class="mono">{{String(index+1).padStart(2,'0')}}</span><TeamLogo :team="team" :size="38"/><div><b>{{team.name}}</b><small>{{team.wins}}–{{team.losses}} · {{team.streak||'—'}}</small></div><strong class="mono">{{team.pct}}</strong></RouterLink><RouterLink to="/teams" class="all-teams">Browse all 30 clubs <ArrowUpRight/></RouterLink></template>
        <EmptyState v-else kind="teams" title="No standings found" detail="Official team records are not available yet."/>
      </aside>
    </section>

    <footer class="source-line"><span><i></i> MLB STATSAPI</span><span><i></i> OPEN-METEO</span><span><i></i> NINTH MODEL</span><p>Real provider data. Missing inputs remain pending.</p></footer>
  </div>
  <LoadingState v-else label="Building today’s read" detail="Loading the official slate, standings, weather and model brief."/>
</template>

<style scoped>
.home{display:grid}.hero{position:relative;min-height:760px;padding:68px 0;overflow:hidden;border:1px solid var(--line);border-radius:22px;background:var(--contrast);isolation:isolate}.hero::before{position:absolute;inset:0;background:radial-gradient(circle at 76% 42%,rgba(214,255,97,.12),transparent 35%),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:auto,96px 100%;content:''}.hero-beam{position:absolute;z-index:0;left:34%;right:-15%;top:58%;height:78px;background:var(--accent);transform:rotate(-24deg);box-shadow:0 0 58px rgba(214,255,97,.2)}.hero-main{position:relative;z-index:4;width:min(64%,930px);padding:clamp(18px,4.5vw,72px)}h1{max-width:930px;margin:24px 0 32px;font-size:clamp(5rem,9vw,9.4rem);line-height:.78;letter-spacing:-.095em}h1 i{font-style:normal;color:var(--accent)}.hero-main>p{max-width:620px;color:var(--muted-strong);font-size:16px;line-height:1.7}.actions{display:flex;gap:10px;margin-top:30px}.actions a,.actions button{min-height:50px;padding:0 18px;display:flex;align-items:center;gap:13px;border:1px solid var(--line-strong);background:rgba(3,5,4,.72);color:var(--text);text-decoration:none;font-size:12px;font-weight:760;text-transform:uppercase;cursor:pointer}.actions a{background:var(--accent);color:#071005;border-color:var(--accent)}.actions svg{width:16px}.hero-object{position:absolute;z-index:2;right:-2%;top:4%}.daily-card{position:absolute;z-index:6;right:34px;bottom:30px;width:min(410px,42%);min-height:330px;padding:25px;display:flex;flex-direction:column;border:1px solid color-mix(in srgb,var(--accent) 30%,var(--line));background:rgba(3,5,4,.84);color:var(--on-contrast);backdrop-filter:blur(18px)}.daily-card header{display:flex;justify-content:space-between;align-items:center;padding-bottom:14px;border-bottom:1px solid #343b35}.daily-card header span{display:flex;gap:9px;align-items:center;color:var(--accent);font:600 11px 'DM Mono'}.daily-card header svg{width:17px}.daily-card header small{color:#aeb4aa;font:11px 'DM Mono'}.brief-match{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;text-align:center;gap:10px;margin:30px 0}.brief-match>div,.brief-match>span{display:flex;align-items:center;flex-direction:column;gap:7px}.brief-match b{font:600 20px 'DM Mono'}.brief-match small,.brief-match em{color:#aeb4aa;font:11px 'DM Mono';font-style:normal}.brief-match strong{color:var(--accent);font-size:14px}.daily-card>a{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:15px;border-top:1px solid #343b35;color:var(--accent);text-decoration:none;font-size:12px;font-weight:760;text-transform:uppercase}.daily-card>a svg{width:16px}.pulse{display:grid;grid-template-columns:repeat(4,1fr);margin-top:12px;border:1px solid var(--line);border-radius:14px;overflow:hidden}.pulse>div{min-height:160px;padding:28px;display:grid;border-right:1px solid var(--line);background:var(--surface)}.pulse>div:last-child{border:0}.pulse span{color:var(--muted);font:500 11px 'DM Mono';text-transform:uppercase}.pulse strong{margin:14px 0 7px;font-size:42px;letter-spacing:-.07em}.pulse small{color:var(--muted);font:11px 'DM Mono'}.split{display:grid;grid-template-columns:1fr 380px;gap:40px;padding:72px 0}.section-head{display:flex;align-items:end;justify-content:space-between;margin-bottom:24px}.section-head h2{margin:8px 0 0;font-size:36px;letter-spacing:-.055em}.section-head>a{display:flex;align-items:center;gap:8px;text-decoration:none;font-size:12px;font-weight:740;text-transform:uppercase}.game-list{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:12px}.standing{min-height:68px;padding:13px 0;display:grid;grid-template-columns:28px 42px 1fr auto;align-items:center;gap:11px;border-top:1px solid var(--line);text-decoration:none}.standing>span{color:var(--muted);font-size:11px}.standing>div{display:flex;flex-direction:column}.standing b{font-size:14px}.standing small{margin-top:4px;color:var(--muted);font-size:12px}.standing strong{font-size:13px}.all-teams{min-height:48px;margin-top:14px;padding:0 14px;display:flex;justify-content:space-between;align-items:center;background:var(--accent);color:#071005;text-decoration:none;font-size:12px;font-weight:760;text-transform:uppercase}.source-line{display:flex;gap:24px;align-items:center;padding:22px 0;border-top:1px solid var(--line);color:var(--muted);font:500 11px 'DM Mono'}.source-line span i{display:inline-block;width:6px;height:6px;margin-right:6px;border-radius:50%;background:var(--green)}.source-line p{margin-left:auto}
@media(max-width:1050px){.hero{min-height:790px}.hero-main{width:76%;padding:60px 28px}.hero-object{right:-22%;top:14%;opacity:.62}.daily-card{right:24px;bottom:24px;width:400px}.split{grid-template-columns:1fr}.split aside{max-width:680px}}
@media(max-width:720px){.hero{min-height:840px;padding:0;border-radius:14px}.hero-main{width:100%;padding:48px 20px}.hero-main h1{font-size:clamp(4.2rem,18vw,6rem)}.hero-object{right:-38%;top:31%;opacity:.46}.daily-card{left:18px;right:18px;bottom:18px;width:auto;min-height:310px}.actions{flex-direction:column}.actions a,.actions button{justify-content:space-between}.pulse{grid-template-columns:1fr 1fr}.pulse>div{min-height:130px;padding:20px}.pulse>div:nth-child(2){border-right:0}.pulse strong{font-size:34px}.split{padding:48px 0}.game-list{grid-template-columns:1fr}.source-line{flex-wrap:wrap}.source-line p{width:100%;margin:0}}
</style>
<style scoped>@media(max-width:720px){.hero-object{right:-44%;top:46%;opacity:.34}.hero-main>p{position:relative;padding:7px 0;background:linear-gradient(90deg,rgba(3,5,4,.84),rgba(3,5,4,.58) 72%,transparent)}}</style>
