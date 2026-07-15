<script setup>
import PlayerHeadshot from '../player/PlayerHeadshot.vue'
import TeamLogo from '../team/TeamLogo.vue'

const props = defineProps({
  stats: { type: Object, default: null },
  game: { type: Object, required: true },
  currentPitcherId: { type: [String, Number], default: null },
  currentBatterId: { type: [String, Number], default: null },
})
const sides = ['away', 'home']
const team = side => props.game[side]
const sideStats = side => props.stats?.[side] || { totals: {}, batters: [], pitchers: [] }
const isCurrentPitcher = pitcher => String(pitcher.id) === String(props.currentPitcherId) || pitcher.current
const isCurrentBatter = batter => String(batter.id) === String(props.currentBatterId) || batter.current
const inningLabel = appearance => `${appearance.half === 'bottom' ? 'B' : 'T'}${appearance.inning || '—'}`
const resultTone = appearance => {
  if (/home_run|triple|double|single|walk|hit_by_pitch/i.test(appearance.event_type || '')) return 'positive'
  return appearance.is_out ? 'out' : 'neutral'
}
</script>

<template>
  <section class="live-stats panel">
    <header class="section-head">
      <div><span class="eyebrow">NINTH / LIVE BOX SCORE</span><h2>What is happening in the game.</h2></div>
      <p>Official workload, batter production and every plate-appearance result. Updated with the live feed.</p>
    </header>

    <div v-if="stats" class="team-totals">
      <article v-for="side in sides" :key="side">
        <TeamLogo :team="team(side)" :size="42"/>
        <div class="team-name"><small>{{ side }}</small><b>{{ team(side).abbr }}</b></div>
        <span><small>R</small><b class="mono">{{ sideStats(side).totals.runs }}</b></span>
        <span><small>H</small><b class="mono">{{ sideStats(side).totals.hits }}</b></span>
        <span><small>HR</small><b class="mono">{{ sideStats(side).totals.home_runs }}</b></span>
        <span><small>BB</small><b class="mono">{{ sideStats(side).totals.walks }}</b></span>
        <span><small>K</small><b class="mono">{{ sideStats(side).totals.strikeouts }}</b></span>
        <span><small>LOB</small><b class="mono">{{ sideStats(side).totals.left_on_base }}</b></span>
        <span class="pitch-total"><small>PITCHES THROWN</small><b class="mono">{{ sideStats(side).totals.pitches }}</b></span>
      </article>
    </div>

    <div v-if="stats" class="workload">
      <section v-for="side in sides" :key="side">
        <header><span>{{ team(side).abbr }} PITCHER WORKLOAD</span><b>{{ sideStats(side).pitchers.length }} USED</b></header>
        <div class="pitcher-list">
          <article v-for="pitcher in sideStats(side).pitchers" :key="pitcher.id" :class="{current:isCurrentPitcher(pitcher)}">
            <PlayerHeadshot :id="pitcher.id" :name="pitcher.name" :size="45"/>
            <div class="person"><small v-if="isCurrentPitcher(pitcher)">ON THE MOUND</small><b>{{ pitcher.name }}</b><span>{{ pitcher.innings }} IP · {{ pitcher.hits }} H · {{ pitcher.earned_runs }} ER · {{ pitcher.walks }} BB · {{ pitcher.strikeouts }} K</span></div>
            <div class="pitch-count"><strong class="mono">{{ pitcher.pitches }}</strong><small>PITCHES</small><span class="mono">{{ pitcher.strikes }} STRIKES</span></div>
          </article>
          <p v-if="!sideStats(side).pitchers.length">Pitcher workload will appear after the first official pitch.</p>
        </div>
      </section>
    </div>

    <div v-if="stats" class="batting-columns">
      <section v-for="side in sides" :key="side">
        <header><span>{{ team(side).abbr }} BATTERS</span><b>GAME LINE / PLATE APPEARANCES</b></header>
        <div class="batter-list">
          <article v-for="batter in sideStats(side).batters" :key="`${batter.id}-${batter.batting_order}`" :class="{current:isCurrentBatter(batter)}">
            <PlayerHeadshot :id="batter.id" :name="batter.name" :size="40"/>
            <div class="batter-name"><small v-if="isCurrentBatter(batter)">AT THE PLATE</small><b>{{ batter.name }}</b><span>{{ batter.position }}<template v-if="batter.substitute"> · SUB</template></span></div>
            <strong class="game-line mono">{{ batter.summary }}</strong>
            <div class="at-bats">
              <span v-for="(appearance,index) in batter.plate_appearances" :key="index" :class="resultTone(appearance)" :title="appearance.description"><small>{{ inningLabel(appearance) }}</small><b>{{ appearance.event }}</b></span>
              <em v-if="!batter.plate_appearances.length">No plate appearance</em>
            </div>
          </article>
        </div>
      </section>
    </div>
    <p v-else class="empty-live">The official live box score is not available yet.</p>
  </section>
</template>

<style scoped>
.live-stats{overflow:hidden}.section-head{display:flex;align-items:end;justify-content:space-between;gap:25px;padding:21px 22px;border-bottom:1px solid var(--line)}.section-head h2{font-size:23px;margin:6px 0 0}.section-head p{max-width:470px;text-align:right;margin:0;font-size:9px;line-height:1.55;color:var(--muted)}
.team-totals{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--line)}.team-totals>article{display:flex;align-items:center;gap:15px;padding:15px 20px}.team-totals>article+article{border-left:1px solid var(--line)}.team-name{display:grid;margin-right:auto}.team-name small{text-transform:uppercase;font:7px 'DM Mono';color:var(--muted)}.team-name b{font-size:15px;margin-top:2px}.team-totals article>span{display:grid;gap:3px;text-align:center;min-width:27px}.team-totals small{font:7px 'DM Mono';color:var(--muted)}.team-totals article>span b{font-size:14px}.team-totals .pitch-total{min-width:82px;padding-left:13px;border-left:1px solid var(--line);text-align:right}.team-totals .pitch-total b{font-size:22px;color:var(--acid)}
.workload,.batting-columns{display:grid;grid-template-columns:1fr 1fr}.workload{border-bottom:1px solid var(--line)}.workload>section,.batting-columns>section{min-width:0;padding:17px 20px}.workload>section+section,.batting-columns>section+section{border-left:1px solid var(--line)}.workload section>header,.batting-columns section>header{display:flex;justify-content:space-between;padding-bottom:8px;border-bottom:1px solid var(--line);font:700 8px 'DM Mono'}.workload section>header b,.batting-columns section>header b{font-size:7px;color:var(--muted)}
.pitcher-list,.batter-list{display:grid;gap:6px;margin-top:8px}.pitcher-list article{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;padding:8px;border:1px solid var(--line);border-left:3px solid var(--blue);background:var(--wash)}.pitcher-list article.current{border-left-color:var(--acid);background:color-mix(in srgb,var(--acid) 6%,var(--wash))}.pitcher-list :deep(.headshot),.batter-list :deep(.headshot){border:0;border-radius:4px;background:var(--surface)}.person{min-width:0;display:grid}.person small,.batter-name small{font:700 6px 'DM Mono';color:var(--acid)}.person b{font-size:10px;margin:3px 0}.person span{font:7px 'DM Mono';color:var(--muted)}.pitch-count{text-align:right;display:grid}.pitch-count strong{font-size:20px;color:var(--acid)}.pitch-count small{font:6px 'DM Mono';color:var(--muted)}.pitch-count span{font-size:6px;margin-top:4px}.pitcher-list>p{padding:12px;margin:0;font-size:8px;color:var(--muted)}
.batting-columns{background:var(--surface)}.batter-list article{display:grid;grid-template-columns:auto minmax(105px,.65fr) auto minmax(150px,1.2fr);align-items:center;gap:9px;padding:7px 8px;border:1px solid var(--line);background:var(--panel)}.batter-list article.current{outline:1px solid var(--acid);background:color-mix(in srgb,var(--acid) 6%,var(--panel))}.batter-name{min-width:0;display:grid}.batter-name b{font-size:9px;margin:2px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.batter-name span{font:6px 'DM Mono';color:var(--muted)}.game-line{font-size:9px;white-space:nowrap}.at-bats{display:flex;justify-content:flex-end;gap:4px;min-width:0;overflow-x:auto}.at-bats>span{flex:none;max-width:90px;padding:5px 6px;border-radius:4px;background:var(--raised);border-left:2px solid var(--muted);display:grid}.at-bats>span.positive{border-left-color:var(--acid);background:color-mix(in srgb,var(--acid) 9%,var(--raised))}.at-bats>span.out{border-left-color:var(--orange)}.at-bats small{font:5px 'DM Mono';color:var(--muted)}.at-bats b{font-size:7px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.at-bats em{font:6px 'DM Mono';font-style:normal;color:var(--muted)}
@media(max-width:1050px){.team-totals,.workload,.batting-columns{grid-template-columns:1fr}.team-totals>article+article,.workload>section+section,.batting-columns>section+section{border-left:0;border-top:1px solid var(--line)}}
@media(max-width:620px){.section-head{align-items:flex-start;flex-direction:column}.section-head p{text-align:left}.team-totals>article{gap:9px;padding:12px}.team-totals :deep(.team-logo){display:none}.team-totals .pitch-total{min-width:66px}.batter-list article{grid-template-columns:auto 1fr auto}.at-bats{grid-column:2/-1;justify-content:flex-start}.workload>section,.batting-columns>section{padding:13px}.person span{line-height:1.5}}
</style>
