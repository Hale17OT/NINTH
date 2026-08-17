<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-vue-next'
import { api } from '../services/api'
import SectionCard from '../components/ui/SectionCard.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import { createSharedPoller } from '../services/polling'

const PAGE_SIZE = 6
const slips = ref([])
const loaded = ref(false)
const uploading = ref(false)
const error = ref('')
const input = ref()
const page = ref(1)
const expandedIds = ref(new Set())
const initializedIds = new Set()
let poller
let warmupTimer

const timestamp = slip => slip.placed_at_iso || slip.imported_at || ''
const sortedSlips = computed(() => [...slips.value].sort((a, b) => timestamp(b).localeCompare(timestamp(a))))
const totalPages = computed(() => Math.max(1, Math.ceil(sortedSlips.value.length / PAGE_SIZE)))
const visibleSlips = computed(() => sortedSlips.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
const activeCount = computed(() => slips.value.filter(slip => slip.active).length)
const isExpanded = slip => expandedIds.value.has(String(slip.id))

function formatSlipDate(slip) {
  const value = timestamp(slip)
  if (!value) return 'Date unavailable'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return slip.placed_at || value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

function toggleSlip(id) {
  const next = new Set(expandedIds.value)
  const key = String(id)
  next.has(key) ? next.delete(key) : next.add(key)
  expandedIds.value = next
}

async function load() {
  try {
    const result = await api.slips()
    slips.value = result
    const next = new Set(expandedIds.value)
    for (const slip of result) {
      const key = String(slip.id)
      if (!initializedIds.has(key)) {
        if (slip.active) next.add(key)
        initializedIds.add(key)
      }
    }
    expandedIds.value = next
  } finally {
    loaded.value = true
  }
}

const choose = () => input.value?.click()
async function importFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  error.value = ''
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    error.value = 'Choose a PDF exported from MelBet.'
    event.target.value = ''
    return
  }
  if (file.size > 9 * 1024 * 1024) {
    error.value = 'The PDF is larger than the 9 MB import limit.'
    event.target.value = ''
    return
  }
  uploading.value = true
  try {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
    await api.importSlip({ filename: file.name, data })
    page.value = 1
    await load()
  } catch (caught) {
    error.value = caught?.message || 'The slip could not be imported.'
  } finally {
    uploading.value = false
    event.target.value = ''
  }
}

watch(totalPages, value => { if (page.value > value) page.value = value })
onMounted(async () => {
  try { await load() } catch (caught) { error.value = caught?.message || 'Slips could not be loaded.' }
  // The first response is the persisted snapshot; pick up the background MLB
  // reconciliation shortly afterward without blocking initial rendering.
  warmupTimer = window.setTimeout(() => { if (document.visibilityState === 'visible') load().catch(() => {}) }, 3000)
  poller = createSharedPoller({ key: 'slips', task: load, interval: 300_000, immediate: false })
  poller.start()
})
onBeforeUnmount(() => { window.clearTimeout(warmupTimer); poller?.stop() })
</script>

<template>
  <div class="slips-page">
    <section class="slips-hero">
      <div>
        <span class="eyebrow">PERSONAL PAPER TRACKER</span>
        <h1>Tracked slips</h1>
        <p>Active tickets stay open. Completed tickets collapse into a compact, chronological archive.</p>
      </div>
      <div class="hero-actions">
        <span><b>{{ activeCount }}</b> ACTIVE</span>
        <button @click="choose" :disabled="uploading">{{ uploading ? 'IMPORTING…' : 'IMPORT PDF' }}</button>
      </div>
      <input ref="input" type="file" accept="application/pdf" hidden @change="importFile">
    </section>

    <p v-if="error" class="error-panel">{{ error }}</p>
    <LoadingState v-if="!loaded" label="Refreshing tracked slips" detail="Matching every selection with the latest official game status and projection alerts."/>
    <SectionCard v-else-if="!slips.length" title="No tracked slips">
      <div class="empty">Import an attached-style PDF to begin monitoring selections.</div>
    </SectionCard>

    <section v-else class="slip-list">
      <article v-for="slip in visibleSlips" :key="slip.id" class="slip" :class="{ active: slip.active, expanded: isExpanded(slip) }">
        <header class="slip-bar">
          <div class="slip-identity">
            <span class="state-dot" :class="{ active: slip.active }"></span>
            <div>
              <span class="eyebrow">{{ slip.active ? 'ACTIVE SLIP' : 'COMPLETED SLIP' }}</span>
              <h2>Slip #{{ slip.id }}</h2>
            </div>
          </div>
          <div class="slip-date">
            <small>PLACED</small>
            <b>{{ formatSlipDate(slip) }}</b>
          </div>
          <div class="money">
            <span><small>STAKE</small><b class="mono">{{ slip.stake ?? '—' }} {{ slip.currency || '' }}</b></span>
            <span><small>POTENTIAL</small><b class="mono">{{ slip.potential_winnings ?? '—' }} {{ slip.currency || '' }}</b></span>
          </div>
          <button class="toggle" type="button" :aria-expanded="isExpanded(slip)" :aria-label="`${isExpanded(slip) ? 'Collapse' : 'Expand'} slip ${slip.id}`" @click="toggleSlip(slip.id)">
            <ChevronUp v-if="isExpanded(slip)" />
            <ChevronDown v-else />
          </button>
        </header>

        <div v-if="isExpanded(slip)" class="slip-details">
          <div class="detail-meta">
            <span>{{ slip.provider }} · {{ slip.bet_type }}</span>
            <span>{{ slip.filename }} · checked {{ new Date(slip.last_checked_at || slip.imported_at).toLocaleString() }}</span>
            <span>Slip prices are metadata only and never enter the model.</span>
          </div>
          <div class="summary">
            <span><small>SELECTIONS</small><b class="mono">{{ slip.selections.length }}</b></span>
            <span><small>WON</small><b class="mono positive">{{ slip.selections.filter(item => item.outcome === 'won').length }}</b></span>
            <span><small>LOST</small><b class="mono negative">{{ slip.selections.filter(item => item.outcome === 'lost').length }}</b></span>
            <span><small>VOID</small><b class="mono void">{{ slip.selections.filter(item => item.outcome === 'void').length }}</b></span>
            <span><small>PENDING</small><b class="mono">{{ slip.selections.filter(item => item.outcome === 'pending').length }}</b></span>
          </div>
          <div class="selections">
            <component :is="pick.game_id ? 'RouterLink' : 'div'" v-for="pick in slip.selections" :key="pick.event_code" :to="pick.game_id ? `/games/${pick.game_id}` : undefined" class="pick">
              <i :class="pick.outcome">{{ pick.outcome === 'won' ? 'W' : pick.outcome === 'lost' ? 'L' : pick.outcome === 'void' ? 'V' : '•' }}</i>
              <div><b>{{ pick.selected_team }}</b><small>{{ pick.team_1 }} vs {{ pick.team_2 }} · {{ pick.selection }}</small></div>
              <span><b :class="pick.outcome">{{ pick.status }}</b><small v-if="pick.final_total_runs != null">Final total {{ pick.final_total_runs }} runs</small><small v-else-if="pick.selected_probability != null">Model {{ Math.round(pick.selected_probability * 100) }}% · confidence {{ pick.model_confidence ?? '—' }}/100</small><small v-else>Slip price {{ pick.slip_odds }}</small></span>
              <p v-for="alert in pick.alerts" :key="alert.message" :class="alert.level">{{ alert.message }}</p>
            </component>
          </div>
        </div>
      </article>
    </section>

    <nav v-if="totalPages > 1" class="pagination" aria-label="Slip pages">
      <button :disabled="page === 1" aria-label="Previous slip page" @click="page--"><ChevronLeft /></button>
      <button v-for="number in totalPages" :key="number" :class="{ current: page === number }" :aria-current="page === number ? 'page' : undefined" @click="page = number">{{ number }}</button>
      <button :disabled="page === totalPages" aria-label="Next slip page" @click="page++"><ChevronRight /></button>
    </nav>
  </div>
</template>

<style scoped>
.loading{padding:45px;text-align:center;border:1px solid var(--line);font:600 8px 'DM Mono';color:var(--muted)}
.slips-page{display:grid;gap:14px;padding-top:20px}.slips-hero{min-height:230px;padding:34px;border:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:24px;background:radial-gradient(circle at 88% 20%,color-mix(in srgb,var(--accent) 28%,transparent),transparent 33%),var(--surface)}h1{font-size:clamp(42px,6vw,76px);letter-spacing:-.07em;margin:12px 0}.slips-hero p{max-width:590px;font-size:11px;line-height:1.6;color:var(--muted)}.hero-actions{display:flex;align-items:center;gap:10px}.hero-actions>span{height:42px;padding:0 14px;border:1px solid var(--line);display:flex;align-items:center;gap:7px;font:600 8px 'DM Mono'}.hero-actions>span b{color:#568900;font-size:15px}.hero-actions button{height:42px;padding:0 17px;border:0;background:var(--ink);color:var(--paper);font:700 8px 'DM Mono';letter-spacing:.08em;cursor:pointer}.error-panel{padding:13px;border:1px solid #d95436;color:#d95436;background:color-mix(in srgb,#d95436 7%,var(--surface));font-size:10px}.empty{padding:35px;text-align:center;color:var(--muted)}.slip-list{display:grid;gap:9px}.slip{border:1px solid var(--line);background:var(--surface);border-left:4px solid #686c66}.slip.active{border-left-color:#568900}.slip-bar{min-height:104px;padding:16px 18px;display:grid;grid-template-columns:minmax(230px,1.1fr) minmax(180px,.8fr) minmax(230px,1fr) 42px;align-items:center;gap:20px}.slip-identity{display:flex;align-items:center;gap:12px}.state-dot{width:9px;height:9px;background:#686c66;border-radius:50%;box-shadow:0 0 0 5px color-mix(in srgb,#686c66 14%,transparent)}.state-dot.active{background:#568900;box-shadow:0 0 0 5px color-mix(in srgb,#568900 14%,transparent)}.slip h2{font-size:19px;letter-spacing:-.03em;margin:5px 0 0}.slip-date,.money span{display:flex;flex-direction:column;gap:5px}.slip-date small,.money small{font:600 7px 'DM Mono';color:var(--muted);letter-spacing:.08em}.slip-date b{font-size:10px}.money{display:grid;grid-template-columns:1fr 1fr;gap:14px}.money b{font-size:11px}.toggle{width:42px;height:42px;border:1px solid var(--line);background:transparent;display:grid;place-items:center;cursor:pointer}.toggle:hover{background:var(--accent)}.toggle svg{width:16px}.slip-details{border-top:1px solid var(--line);padding:16px 18px 18px}.detail-meta{display:flex;justify-content:space-between;gap:14px;font:500 7px 'DM Mono';color:var(--muted)}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:14px 0}.summary span{padding:10px;background:var(--wash);display:flex;flex-direction:column}.summary small{font-size:7px;color:var(--muted)}.summary b{margin-top:5px}.positive{color:#568900}.negative{color:#d95436}.selections{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.pick{display:grid;grid-template-columns:25px minmax(0,1fr) auto;align-items:center;gap:9px;padding:11px;background:var(--wash);border:1px solid var(--line);text-decoration:none}.pick>i{width:23px;height:23px;display:grid;place-items:center;font:800 9px 'DM Mono';font-style:normal;background:var(--surface)}.pick>i.won{background:color-mix(in srgb,#568900 14%,transparent);color:#568900}.pick>i.lost{background:color-mix(in srgb,#d95436 14%,transparent);color:#d95436}.pick>div,.pick>span{display:flex;flex-direction:column}.pick>div b{font-size:10px}.pick small{font-size:8px;color:var(--muted);margin-top:3px}.pick>span{text-align:right}.pick>span b{font-size:8px}.pick>p{grid-column:2/-1;font-size:8px;margin:0;padding:6px;color:#a75c00}.pick>p.critical{color:#d95436}.pagination{display:flex!important;justify-content:center;gap:5px!important;margin:10px 0 30px!important}.pagination button{width:38px;height:38px;border:1px solid var(--line);background:var(--surface);font:700 8px 'DM Mono';cursor:pointer}.pagination button.current{background:var(--ink);color:var(--paper)}.pagination button:disabled{opacity:.35;cursor:not-allowed}
@media(max-width:900px){.slip-bar{grid-template-columns:1fr auto}.slip-date,.money{grid-column:1}.toggle{grid-column:2;grid-row:1/4}.detail-meta{flex-direction:column}.selections{grid-template-columns:1fr}}
@media(max-width:620px){.slips-hero{padding:26px;align-items:flex-start;flex-direction:column}.hero-actions{width:100%;justify-content:space-between}.slip-bar{padding:15px;gap:12px}.money{grid-template-columns:1fr 1fr}.summary{grid-template-columns:repeat(2,1fr)}.pick{grid-template-columns:25px minmax(0,1fr)}.pick>span{grid-column:2;text-align:left}.detail-meta span:nth-child(2){display:none}}
.summary{grid-template-columns:repeat(5,1fr)}.void{color:#7b6a42}.pick>i.void{background:color-mix(in srgb,#b49a62 18%,transparent);color:#7b6a42}@media(max-width:620px){.summary{grid-template-columns:repeat(2,1fr)}}
</style>
