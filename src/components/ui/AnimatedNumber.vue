<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useReducedMotion } from 'motion-v'

const props = defineProps({ value: { type: Number, default: 0 }, decimals: { type: Number, default: 0 }, suffix: { type: String, default: '' } })
const shown = ref(0)
const reduced = useReducedMotion()
let frame

watch(() => props.value, nextValue => {
  window.cancelAnimationFrame(frame)
  const from = shown.value
  const to = Number(nextValue) || 0
  if (reduced.value) { shown.value = to; return }
  const started = performance.now()
  const duration = 520
  const tick = now => {
    const progress = Math.min(1, (now - started) / duration)
    const eased = 1 - Math.pow(1 - progress, 3)
    shown.value = from + (to - from) * eased
    if (progress < 1) frame = window.requestAnimationFrame(tick)
  }
  frame = window.requestAnimationFrame(tick)
}, { immediate: true })

onBeforeUnmount(() => window.cancelAnimationFrame(frame))
</script>

<template><span class="animated-number">{{ shown.toFixed(decimals) }}{{ suffix }}</span></template>

<style scoped>
.animated-number{font:inherit;color:inherit;font-variant-numeric:tabular-nums}
@media(prefers-reduced-motion:reduce){.animated-number{transition:none}}
</style>
