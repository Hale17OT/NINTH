<script setup>
import { computed } from 'vue'
import TeamLogo from '../team/TeamLogo.vue'
import AnimatedNumber from '../ui/AnimatedNumber.vue'

const props = defineProps({ game: { type: Object, required: true }, refreshing: Boolean })
const projection = computed(() => props.game?.projection)
const displayedProbabilities = computed(() => {
  const away = Math.round(Math.max(0, Math.min(1, Number(projection.value?.away_win_probability || 0))) * 1000) / 10
  return { away, home: Number((100 - away).toFixed(1)) }
})
const isFinal = computed(() => /final|completed|game over/i.test(props.game?.status || ''))
const probability = value => `${Math.round(Number(value || 0) * 100)}%`
const projectedTeam = computed(() => projection.value?.projected_side === 'home' ? props.game.home : props.game.away)
const actualSide = computed(() => Number(props.game?.home?.score) === Number(props.game?.away?.score) ? null : Number(props.game?.home?.score) > Number(props.game?.away?.score) ? 'home' : 'away')
const actualWinner = computed(() => actualSide.value ? props.game[actualSide.value] : null)
const pickCorrect = computed(() => actualSide.value && projection.value?.projected_side === actualSide.value)
const updatedAt = computed(() => {
  if (!props.game?.contextUpdatedAt) return 'Awaiting first update'
  return `Checked ${new Date(props.game.contextUpdatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}`
})
const reasonTeam = reason => reason.direction === 'home' ? props.game.home : props.game.away
const liveState = computed(() => projection.value?.game_state)
const liveStateLabel = computed(() => liveState.value ? `${liveState.value.half} ${liveState.value.inning} · ${liveState.value.outs} out${liveState.value.outs === 1 ? '' : 's'}` : 'Awaiting official state')
</script>

<template>
  <section class="live-projection panel" :class="{syncing:refreshing}">
    <header>
      <div><span class="eyebrow">NINTH / {{ isFinal ? 'MODEL AUDIT' : 'MODEL MONITOR' }}</span><h2>{{ isFinal ? 'Final model review' : 'Game projection' }}</h2></div>
      <div class="refresh" :class="{locked:isFinal,syncing:refreshing}"><i></i><span><b>{{ isFinal ? 'FINAL SNAPSHOT' : refreshing ? 'SYNCING LIVE FEED' : '10-SECOND REASSESSMENT' }}</b><small>{{ updatedAt }}</small></span></div>
    </header>

    <template v-if="projection?.available">
      <div v-if="isFinal" class="final-result">
        <div><small>FINAL RESULT</small><b class="mono">{{ game.away.abbr }} {{ game.away.score }}–{{ game.home.score }} {{ game.home.abbr }}</b><span>{{ actualWinner ? `${actualWinner.name} won` : 'Game finished tied' }}</span></div>
        <strong v-if="actualSide" :class="pickCorrect ? 'correct' : 'missed'">{{ pickCorrect ? 'MODEL PICK CORRECT' : 'MODEL PICK MISSED' }}</strong>
      </div>
      <div class="probabilities">
        <div class="team"><TeamLogo :team="game.away" :size="48"/><span><small>{{ game.away.abbr }} {{ isFinal ? 'FORECAST' : 'WIN' }}</small><strong class="mono"><AnimatedNumber :value="displayedProbabilities.away" :decimals="1" suffix="%"/></strong></span></div>
        <div class="pick"><small>{{ isFinal ? 'ORIGINAL MODEL PICK' : 'PROJECTED SIDE' }}</small><b>{{ projectedTeam.name }}</b><span>{{ isFinal ? 'Archived forecast · before the result' : projection.projection_phase === 'live' ? 'Pregame model + official game state' : 'Market-free moneyline forecast' }}</span></div>
        <div class="team home"><span><small>{{ game.home.abbr }} {{ isFinal ? 'FORECAST' : 'WIN' }}</small><strong class="mono"><AnimatedNumber :value="displayedProbabilities.home" :decimals="1" suffix="%"/></strong></span><TeamLogo :team="game.home" :size="48"/></div>
      </div>
      <div class="probability-bar"><i :style="{width: probability(projection.away_win_probability)}"></i><i :style="{width: probability(projection.home_win_probability)}"></i></div>

      <div class="metrics">
        <article><small>MODEL CONFIDENCE</small><strong class="mono">{{ projection.confidence_score }}/100</strong><span>{{ projection.confidence_label }}</span></article>
        <article><small>LIVE INPUT COVERAGE</small><strong class="mono">{{ probability(projection.input_completeness) }}</strong><span>Starter, lineup, bullpen and weather</span></article>
        <article v-if="projection.projection_phase === 'live'"><small>OFFICIAL GAME STATE</small><strong class="mono">{{ game.away.score }}–{{ game.home.score }}</strong><span>{{ liveStateLabel }}</span></article>
        <article v-if="isFinal && actualSide"><small>MODEL RESULT</small><strong class="mono" :class="pickCorrect ? 'result-correct' : 'result-missed'">{{ pickCorrect ? 'CORRECT' : 'INCORRECT' }}</strong><span>Predicted {{ projectedTeam.abbr }} · winner {{ actualWinner.abbr }}</span></article>
        <article v-else-if="projection.movement"><small>PROJECTION MOVEMENT</small><strong class="mono">{{ projection.movement.direction === 'home' ? game.home.abbr : game.away.abbr }}</strong><span>{{ projection.movement.label || 'Latest context adjustment' }}</span></article>
      </div>

      <div v-if="projection.reasons?.length" class="reasons">
        <article v-for="reason in projection.reasons.slice(0, 4)" :key="reason.feature">
          <span :class="reason.direction">{{ reasonTeam(reason).abbr }}</span>
          <div><b>{{ reason.label }}</b><small>Model impact {{ Math.abs(reason.impact).toFixed(2) }}</small></div>
        </article>
      </div>

      <div v-if="projection.circumstance_alerts?.length" class="alerts">
        <article v-for="alert in projection.circumstance_alerts" :key="alert.type + alert.message" :class="alert.level"><b>{{ alert.type.replaceAll('_', ' ') }}</b><span>{{ alert.message }}</span></article>
      </div>

      <p class="scope"><template v-if="isFinal"><b>Audit note:</b> percentages are the archived model forecast, not postgame win chances. The final result is shown separately to score the model pick.</template><template v-else-if="projection.projection_phase === 'live'"><b>Live projection:</b> the trained pregame forecast is adjusted from the official score, inning, outs and baserunner state every 10 seconds. Live results are tracked separately from pregame accuracy until this adjustment layer has enough forward validation.</template><template v-else><b>Projection scope:</b> the trained pregame model is reassessed every five minutes as official starter, lineup, bullpen and weather coverage changes.</template></p>
    </template>
    <p v-else class="empty-live">A projection is unavailable until the model has enough official matchup inputs. No simulated prediction is displayed.</p>
  </section>
</template>

<style scoped>
.live-projection{padding:20px 22px;display:grid;gap:16px;background:radial-gradient(circle at 85% 0,color-mix(in srgb,var(--acid) 10%,transparent),transparent 34%),var(--panel);transition:border-color .35s,box-shadow .35s}.live-projection.syncing{border-color:color-mix(in srgb,var(--acid) 50%,var(--line));box-shadow:0 0 0 1px color-mix(in srgb,var(--acid) 12%,transparent)}
header{display:flex;align-items:center;justify-content:space-between;gap:20px}h2{font-size:22px;margin:4px 0 0}.refresh{display:flex;align-items:center;gap:9px;text-align:right}.refresh>i{width:8px;height:8px;border-radius:50%;background:var(--acid);box-shadow:0 0 11px var(--acid)}.refresh span{display:grid}.refresh b{font:800 9px 'DM Mono';color:var(--acid)}.refresh small{font:8px 'DM Mono';color:var(--muted);margin-top:3px}
.refresh.locked>i{background:var(--muted);box-shadow:none}.refresh.locked b{color:var(--muted)}.final-result{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 16px;border:1px solid var(--line);background:var(--raised);border-radius:11px}.final-result>div{display:grid;gap:3px}.final-result small{font:7px 'DM Mono';color:var(--muted)}.final-result b{font-size:21px}.final-result span{font-size:9px;color:var(--muted)}.final-result>strong{padding:8px 10px;border:1px solid currentColor;border-radius:99px;font:800 8px 'DM Mono'}.final-result .correct,.result-correct{color:var(--acid)!important}.final-result .missed,.result-missed{color:var(--orange)!important}
.probabilities{display:grid;grid-template-columns:1fr minmax(180px,.8fr) 1fr;align-items:center;gap:16px}.team{display:flex;align-items:center;gap:11px}.team span{display:grid}.team small,.pick small,.metrics small{font-size:8px;color:var(--muted)}.team strong{font-size:29px;color:var(--blue)}.team.home{justify-content:flex-end;text-align:right}.team.home strong{color:var(--acid)}.pick{text-align:center;display:grid;gap:4px}.pick b{font-size:14px}.pick span{font-size:9px;color:var(--muted)}
.probability-bar{display:flex;height:7px;border-radius:99px;overflow:hidden;background:var(--raised)}.probability-bar i{transition:width .65s cubic-bezier(.22,.8,.3,1)}.probability-bar i:first-child{background:var(--blue)}.probability-bar i:last-child{background:var(--acid)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}.metrics article{display:grid;gap:5px;padding:12px 14px;border:1px solid var(--line);border-radius:11px;background:var(--raised)}.metrics strong{font-size:18px;color:var(--acid)}.metrics span{font-size:9px;color:var(--muted)}
.reasons{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.reasons article{display:flex;align-items:center;gap:10px;padding:9px 11px;border:1px solid var(--line);border-radius:9px}.reasons article>span{min-width:36px;padding:5px 6px;border-radius:99px;text-align:center;font:800 8px 'DM Mono';background:color-mix(in srgb,var(--blue) 18%,var(--raised));color:var(--blue)}.reasons article>span.home{background:color-mix(in srgb,var(--acid) 16%,var(--raised));color:var(--acid)}.reasons div{display:grid;gap:2px}.reasons b{font-size:10px}.reasons small{font:8px 'DM Mono';color:var(--muted)}
.alerts{display:grid;gap:6px}.alerts article{display:flex;gap:12px;padding:9px 11px;border-left:3px solid var(--orange);background:color-mix(in srgb,var(--orange) 7%,var(--raised));border-radius:5px}.alerts b{font:800 8px 'DM Mono';text-transform:uppercase}.alerts span{font-size:9px;color:var(--muted)}
.scope{margin:0;padding-top:12px;border-top:1px solid var(--line);font-size:9px;line-height:1.55;color:var(--muted)}.scope b{color:var(--text)}
@media(max-width:760px){.probabilities{grid-template-columns:1fr 1fr}.pick{grid-column:1/-1;grid-row:2}.metrics{grid-template-columns:1fr}.reasons{grid-template-columns:1fr}}
@media(max-width:480px){.live-projection{padding:16px}header{align-items:flex-start}.refresh b{font-size:8px}.team strong{font-size:24px}}
</style>
