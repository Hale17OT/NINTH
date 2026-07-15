<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  team: { type: Object, default: () => ({}) },
  size: { type: [Number, String], default: 42 },
})

const failed = ref(false)
const ids = {
  ATH: 133, AZ: 109, ARI: 109, ATL: 144, BAL: 110, BOS: 111, CHC: 112, CWS: 145,
  CIN: 113, CLE: 114, COL: 115, DET: 116, HOU: 117, KC: 118, LAA: 108, LAD: 119,
  MIA: 146, MIL: 158, MIN: 142, NYM: 121, NYY: 147, PHI: 143, PIT: 134, SD: 135,
  SEA: 136, SF: 137, STL: 138, TB: 139, TEX: 140, TOR: 141, WSH: 120,
}
const teamId = computed(() => props.team?.mlbId || (Number.isFinite(Number(props.team?.id)) ? Number(props.team.id) : ids[props.team?.abbr]))
const src = computed(() => teamId.value ? `https://www.mlbstatic.com/team-logos/${teamId.value}.svg` : '')
const label = computed(() => props.team?.name ? `${props.team.name} logo` : `${props.team?.abbr || 'MLB'} logo`)
const compactMark = computed(() => ['SEA','SF','CLE'].includes(String(props.team?.abbr || '').toUpperCase()) || [136,137,114].includes(teamId.value))
const boxSize = computed(() => Math.max(24, Number(props.size) + 8))
const style = computed(() => ({ width: `${boxSize.value}px`, height: `${boxSize.value}px` }))
watch(src, () => { failed.value = false })
</script>

<template>
  <span class="team-logo" :class="{ 'compact-mark': compactMark }" :style="style">
    <img v-if="src && !failed" :src="src" :alt="label" loading="lazy" @error="failed = true">
    <b v-else class="mono">{{ team?.abbr || 'MLB' }}</b>
  </span>
</template>

<style scoped>
.team-logo{display:inline-grid;place-items:center;flex:none;border-radius:8px;background:var(--surface);border:1px solid var(--line);padding:5px;overflow:hidden}.team-logo img{display:block;width:82%;height:82%;max-width:100%;max-height:100%;object-fit:contain;object-position:center;filter:drop-shadow(0 3px 5px rgba(0,0,0,.14))}.team-logo b{font-size:9px;color:var(--acid)}
.team-logo.compact-mark img{width:70%;height:70%;object-position:50% 50%}
</style>
