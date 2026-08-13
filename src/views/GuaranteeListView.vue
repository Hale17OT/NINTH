<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, CheckCircle2, Search, ShieldCheck, TrendingUp } from 'lucide-vue-next'
import { api } from '../services/api'
import PlayerHeadshot from '../components/player/PlayerHeadshot.vue'
import LoadingState from '../components/ui/LoadingState.vue'

const payload = ref(null)
const loading = ref(true)
const error = ref('')
const query = ref('')
const minimumSamples = ref(3)
const market = ref('all')
const evidence = ref('all')
const page = ref(1)
const pageSize = 50

const marketOptions = computed(() => {
  const seen = new Map()
  for (const row of payload.value?.records || []) seen.set(`${row.kind}:${row.prop}`, `${row.kind} · ${row.label}`)
  return [...seen.entries()].sort((a,b) => a[1].localeCompare(b[1]))
})
const records = computed(() => (payload.value?.records || []).filter(row => {
  if (row.samples < minimumSamples.value) return false
  if (market.value !== 'all' && `${row.kind}:${row.prop}` !== market.value) return false
  if (evidence.value !== 'all' && row.evidence !== evidence.value) return false
  return !query.value.trim() || row.player_name.toLowerCase().includes(query.value.trim().toLowerCase())
}))
const proven = computed(() => records.value.filter(row => row.evidence === 'established'))
const pageCount = computed(() => Math.max(1, Math.ceil(records.value.length / pageSize)))
const visibleRecords = computed(() => records.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const headline = computed(() => proven.value[0] || records.value[0])
const totalSettled = computed(() => records.value.reduce((sum,row) => sum + row.samples, 0))
const totalCorrect = computed(() => records.value.reduce((sum,row) => sum + row.correct, 0))
const percent = value => `${(Number(value || 0) * 100).toFixed(1)}%`
const lineLabel = row => `${row.side.toUpperCase()} ${Number(row.line).toFixed(1)}`
watch([query, minimumSamples, market, evidence], () => { page.value = 1 })

onMounted(async () => {
  try { payload.value = await api.playerPropGuarantees(1) }
  catch (caught) { error.value = caught?.message || 'Guarantee history could not be loaded.' }
  finally { loading.value = false }
})
</script>

<template>
  <div class="guarantee-page">
    <section class="guarantee-hero">
      <div><span class="eyebrow">MLB / GUARANTEE LIST</span><h1>What has kept<br><i>being right?</i></h1><p>Every row follows the same player, role, statistic, side and exact line from the first immutable prediction through the latest settled game.</p></div>
      <aside v-if="headline"><span>TOP SAMPLE-AWARE RECORD</span><PlayerHeadshot :player="{id:headline.player_id,name:headline.player_name}" :size="68"/><b>{{ headline.player_name }}</b><strong class="mono">{{ percent(headline.accuracy) }}</strong><small>{{ headline.correct }}/{{ headline.samples }} · {{ headline.label }} {{ lineLabel(headline) }}</small></aside>
    </section>

    <LoadingState v-if="loading" label="Calculating historical consistency" detail="Reading every immutable, settled player-prop prediction."/>
    <section v-else-if="error" class="error-state"><AlertTriangle/><b>Guarantee history unavailable</b><p>{{ error }}</p></section>
    <template v-else>
      <section class="method-warning"><ShieldCheck/><div><b>Historical consistency, not future certainty.</b><p>The rank uses an 80% Wilson lower bound and penalizes records until ten settled observations. A 3/3 start cannot outrank an established 17/20 record merely because it shows 100%.</p></div></section>
      <section class="summary-strip"><article><small>VISIBLE EXACT PICKS</small><b class="mono">{{ records.length }}</b></article><article><small>ESTABLISHED RECORDS</small><b class="mono">{{ proven.length }}</b></article><article><small>SETTLED PREDICTIONS</small><b class="mono">{{ totalSettled }}</b></article><article><small>VISIBLE HIT RATE</small><b class="mono">{{ totalSettled ? percent(totalCorrect/totalSettled) : '—' }}</b></article></section>

      <section class="controls">
        <label><span>FIND PLAYER</span><div><Search :size="15"/><input v-model="query" placeholder="Player name"></div></label>
        <label><span>MINIMUM EVIDENCE</span><select v-model.number="minimumSamples"><option :value="1">All records</option><option :value="3">3+ settled</option><option :value="5">5+ settled</option><option :value="10">10+ established</option></select></label>
        <label><span>MARKET</span><select v-model="market"><option value="all">All player props</option><option v-for="option in marketOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label>
        <label><span>EVIDENCE</span><select v-model="evidence"><option value="all">All maturity levels</option><option value="established">Established</option><option value="developing">Developing</option><option value="early">Early</option></select></label>
      </section>

      <section class="guarantee-list">
        <header><span>PLAYER / EXACT PICK</span><span>ALL-TIME</span><span>RECENT 10</span><span>STREAK</span><span>LOWER BOUND</span><span>EVIDENCE</span></header>
        <article v-for="row in visibleRecords" :key="`${row.player_id}:${row.kind}:${row.prop}:${row.side}:${row.line}`">
          <div class="player"><PlayerHeadshot :player="{id:row.player_id,name:row.player_name}" :size="44"/><span><b>{{ row.player_name }}</b><small>{{ row.kind.toUpperCase() }} · {{ row.label.toUpperCase() }} · {{ lineLabel(row) }}</small></span></div>
          <div class="record"><strong class="mono">{{ percent(row.accuracy) }}</strong><small>{{ row.correct }} / {{ row.samples }} · Brier {{ row.brier_score.toFixed(3) }}</small></div>
          <div><b class="mono">{{ row.recent_10_correct }}/{{ row.recent_10_samples }}</b><small>LAST {{ row.recent_10_samples }}</small></div>
          <div><b class="mono">{{ row.current_streak }}</b><small>CURRENT WINS</small></div>
          <div><b class="mono">{{ percent(row.wilson_lower) }}</b><small>SAMPLE-AWARE</small></div>
          <em :class="row.evidence"><CheckCircle2 v-if="row.evidence==='established'" :size="13"/><TrendingUp v-else :size="13"/>{{ row.evidence.toUpperCase() }}</em>
        </article>
        <div v-if="!records.length" class="empty">No exact player-prop record matches these filters.</div>
      </section>
      <nav v-if="pageCount > 1" class="pagination" aria-label="Guarantee list pages"><button :disabled="page===1" @click="page--">PREVIOUS</button><span>PAGE {{ page }} / {{ pageCount }} · {{ records.length }} EXACT PICKS</span><button :disabled="page===pageCount" @click="page++">NEXT</button></nav>
      <footer>{{ payload.method }} · Updated {{ payload.updated_at ? new Date(payload.updated_at).toLocaleString() : 'pending' }}</footer>
    </template>
  </div>
</template>

<style scoped>
.guarantee-page{display:grid;padding-bottom:45px}.guarantee-hero{min-height:440px;display:grid;grid-template-columns:1fr 340px;gap:55px;align-items:center;border-bottom:1px solid var(--line)}h1{margin:18px 0 25px;font-size:clamp(62px,8vw,108px);line-height:.82;letter-spacing:-.085em}h1 i{font-style:normal;color:var(--accent)}.guarantee-hero>div>p{max-width:680px;color:var(--muted);font-size:14px;line-height:1.7}.guarantee-hero aside{min-height:295px;padding:25px;display:flex;flex-direction:column;align-items:flex-start;background:var(--contrast);color:var(--on-contrast);border-top:4px solid var(--accent)}.guarantee-hero aside>span{font:700 7px 'DM Mono';color:var(--accent)}.guarantee-hero aside>.headshot{margin:28px 0 12px}.guarantee-hero aside>b{font-size:18px}.guarantee-hero aside>strong{margin-top:auto;font-size:48px;letter-spacing:-.08em;color:var(--accent)}.guarantee-hero aside>small{font:600 7px 'DM Mono';color:#aeb4aa}.method-warning{margin:24px 0;display:flex;gap:13px;padding:16px;border:1px solid color-mix(in srgb,var(--accent) 40%,var(--line));background:color-mix(in srgb,var(--accent) 7%,var(--surface))}.method-warning svg{color:var(--acid);flex:none}.method-warning b{font-size:11px}.method-warning p{margin:4px 0 0;color:var(--muted);font-size:9px;line-height:1.5}.summary-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}.summary-strip article{padding:18px;background:var(--surface);display:grid;gap:8px}.summary-strip small,.controls label>span{font:700 7px 'DM Mono';letter-spacing:.07em;color:var(--muted)}.summary-strip b{font-size:26px}.controls{display:grid;grid-template-columns:1.2fr repeat(3,1fr);gap:8px;padding:24px 0 14px}.controls label{display:grid;gap:7px}.controls label>div,.controls select{height:42px;border:1px solid var(--line);background:var(--surface);color:var(--text)}.controls label>div{display:flex;align-items:center;gap:9px;padding:0 11px}.controls input{width:100%;border:0;outline:0;background:transparent;color:var(--text);font-size:10px}.controls select{width:100%;padding:0 10px;font-size:9px}.guarantee-list{border:1px solid var(--line)}.guarantee-list>header,.guarantee-list>article{display:grid;grid-template-columns:minmax(280px,2fr) repeat(4,minmax(90px,.7fr)) minmax(110px,.8fr);align-items:center;gap:12px;padding:11px 14px}.guarantee-list>header{background:var(--contrast);color:#9ba297;font:700 6px 'DM Mono';letter-spacing:.08em}.guarantee-list>article{min-height:71px;border-bottom:1px solid var(--line)}.guarantee-list>article:last-of-type{border:0}.guarantee-list>article:hover{background:var(--wash)}.player{min-width:0;display:flex;align-items:center;gap:10px}.player>span,.guarantee-list article>div:not(.player){display:grid;gap:4px}.player b{overflow:hidden;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.player small,.guarantee-list article>div small{font:600 6px 'DM Mono';color:var(--muted)}.record strong{font-size:20px;color:var(--acid)}.guarantee-list article>div>b{font-size:13px}.guarantee-list em{justify-self:start;display:flex;align-items:center;gap:5px;padding:6px 7px;font:700 6px 'DM Mono';font-style:normal;background:var(--wash);color:var(--muted)}.guarantee-list em.established{background:color-mix(in srgb,var(--accent) 17%,var(--surface));color:var(--acid)}.empty,.error-state{padding:40px;text-align:center;color:var(--muted)}.error-state{margin-top:30px;border:1px solid var(--line)}.error-state b{display:block;margin:10px;color:var(--text)}.pagination{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--line)}.pagination button{padding:9px 12px;border:1px solid var(--line);background:var(--surface);color:var(--text);font:700 7px 'DM Mono';cursor:pointer}.pagination button:disabled{opacity:.35;cursor:not-allowed}.pagination span{font:700 7px 'DM Mono';color:var(--muted)}footer{padding:15px 0;font:600 6px 'DM Mono';color:var(--muted)}@media(max-width:1050px){.guarantee-list{overflow-x:auto}.guarantee-list>header,.guarantee-list>article{min-width:1000px}.controls{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){.guarantee-hero{grid-template-columns:1fr;padding:38px 0}.summary-strip{grid-template-columns:repeat(2,1fr)}.controls{grid-template-columns:1fr}.pagination span{font-size:5px}h1{font-size:56px}}
</style>
