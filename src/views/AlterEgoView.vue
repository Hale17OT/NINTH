<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, BrainCircuit, Check, ChevronDown, ChevronUp, Download, RefreshCw, ShieldCheck, Target } from 'lucide-vue-next'
import { api } from '../services/api'
import LoadingState from '../components/ui/LoadingState.vue'

const data = ref(null)
const loaded = ref(false)
const importing = ref(false)
const importingAll = ref(false)
const importProgress = ref(null)
const error = ref('')
const notice = ref('')
const batchWarning = ref('')
const helperVersion = ref('')
const activeBreakdown = ref('markets')
const openSlip = ref('')
let requestId = ''
let batchRequestId = ''
let importTimeout
let batchTimeout

const overview = computed(() => data.value?.overview || {})
const breakdown = computed(() => data.value?.breakdowns?.[activeBreakdown.value] || [])
const percent = value => value == null ? '—' : `${Math.round(Number(value) * 100)}%`
const money = value => `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} ETB`
const signedMoney = value => `${Number(value || 0) >= 0 ? '+' : '−'}${money(Math.abs(Number(value || 0)))}`
const statusClass = value => String(value || '').toLowerCase()
const placed = value => {
  const match = String(value || '').match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})\s*\/\s*(\d{1,2}:\d{2})$/)
  if (!match) return String(value || '') || 'Unknown'
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${Number(match[1])} ${months[Number(match[2]) - 1] || match[2]} ${match[3]} · ${match[4]}`
}

async function load() {
  error.value = ''
  try { data.value = await api.alterEgo() }
  catch (cause) { error.value = cause.message || 'Alter Ego history could not be loaded.' }
  finally { loaded.value = true }
}

function startImport() {
  error.value = ''
  notice.value = ''
  batchWarning.value = ''
  importing.value = true
  requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  window.postMessage({ source: 'NINTH_APP', type: 'NINTH_MELBET_HISTORY_REQUEST', requestId }, window.location.origin)
  clearTimeout(importTimeout)
  importTimeout = window.setTimeout(() => {
    importing.value = false
    error.value = 'The helper did not answer. Reload NINTH MelBet Helper, refresh both this page and MelBet Bet history, reselect the slip, and try again.'
  }, 15000)
}

function startImportAll() {
  error.value = ''
  notice.value = ''
  batchWarning.value = ''
  importingAll.value = true
  importProgress.value = { scanned: 0, expected: 0, imported: 0, skipped: 0, failed: 0 }
  batchRequestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  window.postMessage({
    source: 'NINTH_APP', type: 'NINTH_MELBET_HISTORY_ALL_REQUEST', requestId: batchRequestId,
    existingSlipIds: (data.value?.slips || []).map(slip => String(slip.slip_id)),
  }, window.location.origin)
  clearTimeout(batchTimeout)
  batchTimeout = window.setTimeout(() => {
    importingAll.value = false
    error.value = 'The full-history scan stopped answering. Refresh MelBet Bet history, keep the current filter applied, and try Import all missing again.'
  }, 10 * 60 * 1000)
}

async function historyResult(event) {
  if (event.source !== window || event.origin !== window.location.origin || event.data?.source !== 'NINTH_EXTENSION') return
  if (event.data?.type === 'NINTH_MELBET_HISTORY_ALL_PROGRESS' && event.data?.requestId === batchRequestId) {
    importProgress.value = event.data
    return
  }
  if (event.data?.type === 'NINTH_MELBET_HISTORY_ALL_RESULT' && event.data?.requestId === batchRequestId) {
    clearTimeout(batchTimeout)
    helperVersion.value = event.data.helperVersion || helperVersion.value
    if (!event.data.ok) {
      importingAll.value = false
      importProgress.value = null
      error.value = event.data.error || 'MelBet history could not be imported.'
      return
    }
    try {
      if (event.data.slips?.length) {
        const response = await api.importMelbetHistoryBatch({ slips: event.data.slips })
        data.value = response.analysis
      }
      const imported = event.data.slips?.length || 0
      const skipped = Number(event.data.skipped || 0)
      notice.value = imported
        ? `Imported ${imported} missing slip${imported === 1 ? '' : 's'}; ${skipped} already stored.`
        : `All ${skipped || event.data.scanned || 0} slips in the current MelBet filter are already stored.`
      if (event.data.failures?.length) batchWarning.value = `${event.data.failures.length} slip${event.data.failures.length === 1 ? '' : 's'} could not be read and were left unimported. Run Import all missing again to retry them.`
    } catch (cause) {
      error.value = cause.message || 'NINTH could not save the imported MelBet history batch.'
    } finally {
      importingAll.value = false
      importProgress.value = null
    }
    return
  }
  if (event.data?.type !== 'NINTH_MELBET_HISTORY_RESULT' || event.data?.requestId !== requestId) return
  clearTimeout(importTimeout)
  helperVersion.value = event.data.helperVersion || ''
  if (!event.data.ok) {
    importing.value = false
    error.value = event.data.error || 'The selected MelBet slip could not be imported.'
    return
  }
  try {
    data.value = await api.importMelbetHistory({ slip: event.data.slip })
    const legCount = event.data.slip?.legs?.filter(leg => !leg.is_bonus).length || 0
    notice.value = `Slip ${event.data.slip?.slip_id} imported with ${legCount} complete betting legs.`
    openSlip.value = String(event.data.slip?.slip_id || '')
  } catch (cause) {
    error.value = cause.message || 'NINTH could not save the selected MelBet slip.'
  } finally { importing.value = false }
}

onMounted(() => { window.addEventListener('message', historyResult); load() })
onBeforeUnmount(() => { clearTimeout(importTimeout); clearTimeout(batchTimeout); window.removeEventListener('message', historyResult) })
</script>

<template>
  <div class="alter-page">
    <section class="hero">
      <div>
        <span class="eyebrow"><BrainCircuit :size="13"/> ALTER EGO / BETTING MIRROR</span>
        <h1>See the pattern<br>behind the result.</h1>
        <p>Import the selected MelBet slip, compare what wins with what breaks the card, and turn settled evidence into practical builder guardrails.</p>
      </div>
      <div class="import-panel">
        <span class="connection"><i></i> LOCAL HELPER{{ helperVersion ? ` · v${helperVersion}` : '' }}</span>
        <ol><li><b>1</b><span>Open MelBet <strong>Bet history</strong></span></li><li><b>2</b><span>Select one slip so its drawer is open</span></li><li><b>3</b><span>Import; duplicates update by slip number</span></li></ol>
        <div class="import-actions">
          <button type="button" :disabled="importing || importingAll" @click="startImport"><RefreshCw v-if="importing" class="spin" :size="15"/><Download v-else :size="15"/>{{ importing ? 'READING…' : 'SELECTED SLIP' }}</button>
          <button class="secondary" type="button" :disabled="importing || importingAll" @click="startImportAll"><RefreshCw :class="{ spin: importingAll }" :size="15"/>{{ importingAll ? 'SCANNING…' : 'ALL MISSING' }}</button>
        </div>
        <small v-if="importingAll && importProgress">{{ importProgress.scanned || 0 }}{{ importProgress.expected ? ` / ${importProgress.expected}` : '' }} scanned · {{ importProgress.imported || 0 }} imported · {{ importProgress.skipped || 0 }} skipped</small>
        <small v-else>Read-only. Alter Ego cannot place or modify a wager.</small>
      </div>
    </section>

    <p v-if="error" class="message error"><AlertTriangle :size="15"/>{{ error }}</p>
    <p v-if="notice" class="message success"><Check :size="15"/>{{ notice }}</p>
    <p v-if="batchWarning" class="message warning"><AlertTriangle :size="15"/>{{ batchWarning }}</p>
    <LoadingState v-if="!loaded" label="Loading Alter Ego" detail="Reading locally imported, settled MelBet history."/>

    <template v-else>
      <section class="metrics">
        <article><span>FULL-SLIP HIT RATE</span><b>{{ percent(overview.slip_hit_rate) }}</b><small>{{ overview.won_slips || 0 }} of {{ overview.settled_slips || 0 }} settled slips</small></article>
        <article><span>LEG HIT RATE</span><b>{{ percent(overview.leg_hit_rate) }}</b><small>{{ overview.won_legs || 0 }} of {{ overview.settled_legs || 0 }} settled legs</small></article>
        <article><span>NEAR MISSES</span><b>{{ overview.near_misses || 0 }}</b><small>cards lost by exactly one leg</small></article>
        <article :class="Number(overview.net || 0) >= 0 ? 'positive' : 'negative'"><span>SETTLED NET</span><b>{{ signedMoney(overview.net) }}</b><small>{{ percent(overview.roi) }} ROI · {{ money(overview.stake) }} staked</small></article>
      </section>

      <section v-if="!data?.slips?.length" class="empty-state">
        <Target :size="28"/><div><b>No slips in the mirror yet</b><p>Keep a selected MelBet slip open and use Import selected slip. Import wins and losses to avoid selection bias.</p></div>
      </section>

      <div v-else class="analysis-grid">
        <section class="panel advice-panel">
          <header><div><span>ALTER EGO'S READ</span><h2>What to change next</h2></div><ShieldCheck :size="22"/></header>
          <article v-for="(item, index) in data.advice" :key="item.title" :class="['advice', item.severity]"><i>{{ String(index + 1).padStart(2, '0') }}</i><div><b>{{ item.title }}</b><p>{{ item.detail }}</p></div></article>
          <p class="responsible">Evidence support, not a guarantee. Use fixed stakes and never chase losses.</p>
        </section>

        <section class="panel breakdown-panel">
          <header><div><span>SETTLED LEG AUDIT</span><h2>Where cards hold or break</h2></div><Activity :size="21"/></header>
          <div class="tabs"><button v-for="tab in ['markets','sides','odds']" :key="tab" :class="{ active: activeBreakdown === tab }" @click="activeBreakdown=tab">{{ tab }}</button></div>
          <div class="breakdown-head"><span>GROUP</span><span>RECORD</span><span>HIT RATE</span></div>
          <div v-for="row in breakdown" :key="row.label" class="breakdown-row">
            <div><b>{{ row.label }}</b><small>{{ row.settled }} settled leg{{ row.settled === 1 ? '' : 's' }}</small></div>
            <span>{{ row.wins }}–{{ row.losses }}</span>
            <div class="rate"><b>{{ percent(row.hit_rate) }}</b><i><em :style="{ width: `${(row.hit_rate || 0) * 100}%` }"></em></i></div>
          </div>
        </section>
      </div>

      <section v-if="data?.slips?.length" class="history">
        <header><div><span>IMPORTED HISTORY</span><h2>Slip-level evidence</h2></div><b>{{ data.slips.length }} SLIP{{ data.slips.length === 1 ? '' : 'S' }}</b></header>
        <article v-for="slip in data.slips" :key="slip.slip_id" class="slip-card">
          <button class="slip-summary" @click="openSlip = openSlip === String(slip.slip_id) ? '' : String(slip.slip_id)">
            <span :class="['status', statusClass(slip.status)]">{{ slip.status }}</span>
            <div><small>BET SLIP</small><b>№ {{ slip.slip_id }}</b></div>
            <div><small>PLACED</small><b>{{ placed(slip.placed_at) || 'Unknown' }}</b></div>
            <div><small>STRUCTURE</small><b>{{ slip.leg_count }} legs · {{ Number(slip.total_odds || 0).toFixed(3) }} odds</b></div>
            <div><small>STAKE / RETURN</small><b>{{ money(slip.stake) }} / {{ slip.status === 'win' ? money(slip.potential_winnings) : money(0) }}</b></div>
            <ChevronUp v-if="openSlip === String(slip.slip_id)" :size="17"/><ChevronDown v-else :size="17"/>
          </button>
          <div v-if="openSlip === String(slip.slip_id)" class="legs">
            <div v-for="leg in slip.legs" :key="`${slip.slip_id}-${leg.index}`" :class="['leg', { bonus: leg.is_bonus }]">
              <span :class="['leg-state', statusClass(leg.status)]"><ArrowUpRight v-if="leg.status === 'win'" :size="13"/><ArrowDownRight v-else-if="leg.status === 'loss'" :size="13"/>{{ leg.status }}</span>
              <div><b>{{ leg.selection }}</b><small>{{ leg.event || leg.league }} · {{ leg.market }} / {{ leg.side }}</small></div>
              <strong>{{ leg.odds ? Number(leg.odds).toFixed(3) : '—' }}</strong>
            </div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.import-actions{display:grid;grid-template-columns:1fr 1fr;gap:7px}.import-panel .import-actions button{font-size:7px;letter-spacing:.06em;gap:7px}.import-panel button.secondary{border:1px solid var(--ink);background:transparent;color:var(--text)}.message.warning{color:#9b6500;background:color-mix(in srgb,#c98300 8%,var(--surface))}
.alter-page{display:grid;gap:14px;padding-top:20px}.hero{min-height:330px;padding:36px 40px;border:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1.35fr) minmax(340px,.65fr);gap:38px;align-items:center;background:radial-gradient(circle at 17% 28%,color-mix(in srgb,var(--accent) 19%,transparent),transparent 34%),linear-gradient(135deg,var(--surface),var(--paper))}.eyebrow,.panel header span,.history header span{display:flex;align-items:center;gap:7px;font:650 7px 'DM Mono';letter-spacing:.13em;color:var(--muted)}h1{font-size:clamp(48px,6.5vw,88px);line-height:.88;letter-spacing:-.075em;margin:19px 0}.hero>div>p{max-width:650px;margin:0;color:var(--muted);font-size:11px;line-height:1.7}.import-panel{padding:22px;border:1px solid var(--ink);background:var(--surface);box-shadow:9px 9px 0 color-mix(in srgb,var(--ink) 11%,transparent)}.connection{font:650 7px 'DM Mono';letter-spacing:.1em;display:flex;align-items:center;gap:7px}.connection i{width:7px;height:7px;border-radius:50%;background:#5f9200;box-shadow:0 0 0 4px color-mix(in srgb,#5f9200 13%,transparent)}ol{list-style:none;margin:20px 0;padding:0;display:grid;gap:11px}li{display:flex;align-items:center;gap:11px;font-size:9px;color:var(--muted)}li>b{width:23px;height:23px;display:grid;place-items:center;border:1px solid var(--line);font:700 8px 'DM Mono';color:var(--text)}li strong{color:var(--text)}.import-panel button{width:100%;height:45px;border:0;background:var(--ink);color:var(--paper);display:flex;align-items:center;justify-content:center;gap:9px;font:750 8px 'DM Mono';letter-spacing:.08em;cursor:pointer}.import-panel button:disabled{opacity:.65}.import-panel small{display:block;margin-top:10px;text-align:center;font-size:7px;color:var(--muted)}.spin{animation:spin .8s linear infinite}.message{min-height:44px;padding:0 14px;border:1px solid;display:flex;align-items:center;gap:9px;font-size:9px;margin:0}.message.error{color:#c94831;background:color-mix(in srgb,#c94831 7%,var(--surface))}.message.success{color:#4c7c00;background:color-mix(in srgb,#69a600 8%,var(--surface))}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.metrics article{min-height:122px;padding:18px;border:1px solid var(--line);background:var(--surface);display:flex;flex-direction:column}.metrics span{font:650 7px 'DM Mono';letter-spacing:.09em;color:var(--muted)}.metrics b{font-size:31px;letter-spacing:-.055em;margin:14px 0 5px}.metrics small{font-size:8px;color:var(--muted)}.metrics .positive{border-top:3px solid #679c00}.metrics .negative{border-top:3px solid #c94831}.metrics .positive b{color:#568900}.metrics .negative b{color:#c94831}.empty-state{padding:38px;border:1px dashed var(--line);display:flex;align-items:center;justify-content:center;gap:17px;background:var(--surface)}.empty-state b{font-size:17px}.empty-state p{max-width:500px;margin:5px 0 0;color:var(--muted);font-size:9px}.analysis-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.panel,.history{border:1px solid var(--line);background:var(--surface)}.panel>header,.history>header{padding:19px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}.panel h2,.history h2{font-size:21px;letter-spacing:-.04em;margin:6px 0 0}.advice{padding:15px 20px;display:grid;grid-template-columns:30px 1fr;gap:11px;border-bottom:1px solid var(--line)}.advice>i{width:26px;height:26px;display:grid;place-items:center;background:var(--wash);font:700 7px 'DM Mono';font-style:normal}.advice.high>i{background:color-mix(in srgb,#c94831 13%,var(--surface));color:#c94831}.advice.medium>i{background:color-mix(in srgb,#c98300 14%,var(--surface));color:#a46b00}.advice b{font-size:11px}.advice p{margin:5px 0 0;color:var(--muted);font-size:9px;line-height:1.55}.responsible{margin:0;padding:13px 20px;font:500 7px 'DM Mono';color:var(--muted)}.tabs{height:40px;display:flex;border-bottom:1px solid var(--line)}.tabs button{flex:1;border:0;border-right:1px solid var(--line);background:transparent;color:var(--muted);font:650 7px 'DM Mono';text-transform:uppercase;cursor:pointer}.tabs button.active{background:var(--ink);color:var(--paper)}.breakdown-head,.breakdown-row{display:grid;grid-template-columns:minmax(0,1fr) 70px 130px;align-items:center;gap:10px}.breakdown-head{padding:10px 16px;background:var(--wash);font:600 6px 'DM Mono';color:var(--muted)}.breakdown-row{min-height:58px;padding:9px 16px;border-top:1px solid var(--line)}.breakdown-row>div:first-child{display:flex;flex-direction:column;gap:4px}.breakdown-row b{font-size:9px}.breakdown-row small{font-size:7px;color:var(--muted)}.breakdown-row>span{font:700 9px 'DM Mono'}.rate{display:flex;align-items:center;gap:8px}.rate b{width:32px;text-align:right}.rate i{height:5px;flex:1;background:var(--wash);overflow:hidden}.rate em{height:100%;display:block;background:var(--accent)}.history>header>b{font:700 7px 'DM Mono';color:var(--muted)}.slip-card{border-bottom:1px solid var(--line)}.slip-summary{width:100%;min-height:76px;padding:12px 17px;border:0;background:transparent;color:var(--text);display:grid;grid-template-columns:68px 1fr 1.2fr 1.2fr 1.2fr 20px;align-items:center;gap:14px;text-align:left;cursor:pointer}.slip-summary:hover{background:var(--wash)}.slip-summary>div{display:flex;flex-direction:column;gap:5px}.slip-summary small{font:600 6px 'DM Mono';color:var(--muted);letter-spacing:.08em}.slip-summary b{font-size:9px}.status,.leg-state{font:700 7px 'DM Mono';text-transform:uppercase}.status{width:54px;height:25px;display:grid;place-items:center;background:var(--wash)}.status.win,.leg-state.win{color:#568900}.status.loss,.leg-state.loss{color:#c94831}.status.pending,.leg-state.pending{color:#a46b00}.legs{padding:7px 17px 14px;background:var(--wash);display:grid;gap:5px}.leg{min-height:54px;padding:9px 11px;display:grid;grid-template-columns:68px minmax(0,1fr) 48px;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line)}.leg-state{display:flex;align-items:center;gap:3px}.leg>div{display:flex;flex-direction:column;gap:5px}.leg>div b{font-size:9px}.leg>div small{font-size:7px;color:var(--muted)}.leg>strong{text-align:right;font:700 9px 'DM Mono'}.leg.bonus{opacity:.65}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1050px){.hero{grid-template-columns:1fr;padding:30px}.metrics{grid-template-columns:repeat(2,1fr)}.analysis-grid{grid-template-columns:1fr}.slip-summary{grid-template-columns:60px 1fr 1fr 1fr 20px}.slip-summary>div:nth-of-type(4){display:none}}
@media(max-width:620px){.alter-page{padding-top:13px}.hero{padding:24px 20px;gap:25px}.hero h1{font-size:50px}.import-panel{padding:17px;box-shadow:none}.metrics{grid-template-columns:1fr 1fr}.metrics article{min-height:108px;padding:14px}.metrics b{font-size:25px}.breakdown-head,.breakdown-row{grid-template-columns:minmax(0,1fr) 55px 100px}.slip-summary{grid-template-columns:54px 1fr 20px;gap:9px}.slip-summary>div:nth-of-type(n+2){display:none}.leg{grid-template-columns:58px minmax(0,1fr)}.leg>strong{grid-column:2;text-align:left}.panel>header,.history>header{padding:16px}.advice{padding:14px 16px}}
</style>
