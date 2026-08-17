<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },
  label: { type: String, default: '' },
  detail: { type: String, default: '' },
  size: { type: Number, default: 190 },
  decimals: { type: Number, default: 1 },
})

const root = ref(null)
const visible = ref(false)
const displayed = ref(0)
let observer
let frame

const target = computed(() => {
  const raw = Number(props.value)
  if (!Number.isFinite(raw)) return 0
  return Math.max(0, Math.min(100, raw <= 1 ? raw * 100 : raw))
})
const formatted = computed(() => displayed.value.toFixed(Math.max(0, props.decimals)))
const digits = computed(() => formatted.value.length)
const dash = computed(() => `${displayed.value} ${100 - displayed.value}`)
const ringStyle = computed(() => ({
  '--ring-size': `${Math.max(96, props.size)}px`,
  '--number-size': digits.value >= 5 ? '16cqi' : digits.value >= 4 ? '20cqi' : '24cqi',
}))

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const animateTo = next => {
  cancelAnimationFrame(frame)
  if (!visible.value || reducedMotion()) { displayed.value = next; return }
  const from = displayed.value
  const change = next - from
  const start = performance.now()
  const duration = 760
  const tick = now => {
    const elapsed = Math.min(1, (now - start) / duration)
    const eased = 1 - Math.pow(1 - elapsed, 3)
    displayed.value = from + change * eased
    if (elapsed < 1) frame = requestAnimationFrame(tick)
    else displayed.value = next
  }
  frame = requestAnimationFrame(tick)
}

watch(target, animateTo)
watch(visible, value => { if (value) animateTo(target.value) })
onMounted(async () => {
  await nextTick()
  if (!('IntersectionObserver' in window)) { visible.value = true; return }
  observer = new IntersectionObserver(([entry]) => {
    if (!entry?.isIntersecting) return
    visible.value = true
    observer?.disconnect()
  }, { threshold: .28 })
  observer.observe(root.value)
})
onBeforeUnmount(() => { observer?.disconnect(); cancelAnimationFrame(frame) })
</script>

<template>
  <div ref="root" class="probability-ring" :style="ringStyle" role="img" :aria-label="`${target.toFixed(decimals)} percent${label ? `, ${label}` : ''}`">
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle class="track" cx="60" cy="60" r="51" pathLength="100" />
      <circle class="value" cx="60" cy="60" r="51" pathLength="100" :stroke-dasharray="dash" />
    </svg>
    <div class="ring-copy">
      <strong><span>{{ formatted }}</span><sup>%</sup></strong>
      <span v-if="label" class="ring-label">{{ label }}</span>
      <small v-if="detail" class="ring-detail">{{ detail }}</small>
    </div>
  </div>
</template>

<style scoped>
.probability-ring{width:min(100%,var(--ring-size));aspect-ratio:1;position:relative;container-type:inline-size}.probability-ring svg{width:100%;height:100%;transform:rotate(-90deg);overflow:visible}.probability-ring circle{fill:none;stroke-width:6}.probability-ring .track{stroke:var(--line)}.probability-ring .value{stroke:var(--sport,var(--accent));stroke-linecap:round;transition:stroke .22s}.ring-copy{position:absolute;inset:17%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;min-width:0}.ring-copy strong{display:flex;align-items:flex-start;justify-content:center;max-width:100%;font:800 var(--number-size)/.9 'DM Mono';letter-spacing:-.09em;white-space:nowrap}.ring-copy strong span{min-width:0}.ring-copy sup{margin:.12em 0 0 .14em;font-size:.36em;letter-spacing:0;color:var(--sport,var(--accent))}.ring-label{width:100%;margin-top:7%;font:800 clamp(6px,5.3cqi,10px)/1.15 'DM Mono';letter-spacing:.02em;color:var(--sport,var(--accent));text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ring-detail{width:112%;margin-top:4%;font:600 clamp(5px,4cqi,8px)/1.35 'DM Mono';color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}@media(prefers-reduced-motion:reduce){.probability-ring .value{transition:none}}
</style>
