<script setup>
import { AnimatePresence, motion, useReducedMotion } from 'motion-v'
import ProbabilityRing from '../charts/ProbabilityRing.vue'

const props = defineProps({
  probability: { type: Number, default: 0 },
  available: { type: Boolean, default: true },
  eyebrow: { type: String, default: 'JOINT MODEL CONFIDENCE' },
  title: { type: String, required: true },
  description: { type: String, required: true },
  detail: { type: String, default: '' },
  selected: { type: Number, default: 0 },
  target: { type: Number, default: 0 },
  average: { type: Number, default: 0 },
  fourthLabel: { type: String, default: 'EVIDENCE' },
  fourthValue: { type: String, default: 'MODEL' },
})
const reduced = useReducedMotion()
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`
</script>

<template>
  <motion.section class="unified-builder-score" layout :transition="{ layout: { type: 'spring', stiffness: 260, damping: 30 } }">
    <ProbabilityRing class="score-ring" :value="available && selected ? probability : 0" :size="112" :label="available ? (selected ? 'all legs' : 'no card') : 'locked'" :detail="available ? (selected ? 'joint model' : 'select legs') : 'awaiting evidence'"/>
    <div class="score-copy">
      <span class="eyebrow">{{ eyebrow }}</span>
      <AnimatePresence mode="wait">
        <motion.h2 :key="title" :initial="reduced ? false : { opacity: 0, y: 7 }" :animate="{ opacity: 1, y: 0 }" :exit="reduced ? undefined : { opacity: 0, y: -5 }">{{ title }}</motion.h2>
      </AnimatePresence>
      <p>{{ description }}</p><small v-if="detail">{{ detail }}</small>
    </div>
    <motion.div class="score-metrics" layout>
      <span><small>LEGS / TARGET</small><b class="mono">{{ selected }} / {{ target }}</b></span>
      <span><small>JOINT MODEL</small><b class="mono">{{ selected && available ? pct(probability) : '—' }}</b></span>
      <span><small>TYPICAL LEG</small><b class="mono">{{ selected ? pct(average) : '—' }}</b></span>
      <span><small>{{ fourthLabel }}</small><b class="mono">{{ fourthValue }}</b></span>
    </motion.div>
    <div class="score-actions"><slot name="actions" /></div>
  </motion.section>
</template>

<style scoped>
.unified-builder-score{display:grid;grid-template-columns:auto minmax(260px,1fr) auto auto;gap:22px;align-items:center;padding:22px 25px;background:var(--contrast);color:var(--on-contrast)}.score-ring{width:112px;--muted:#a8afa4}.score-copy h2{margin:7px 0;font-size:20px}.score-copy p{max-width:540px;margin:0;color:#aeb3aa;font-size:11px;line-height:1.55}.score-copy>small{display:block;max-width:560px;margin-top:7px;color:#d5d8d1;font:500 10px/1.5 'DM Mono'}.score-copy .eyebrow{color:var(--sport,var(--accent))}.score-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:#343931}.score-metrics span{min-width:100px;padding:12px;display:flex;flex-direction:column;gap:5px;background:#20241e}.score-metrics small{font:500 10px 'DM Mono';color:#949a90}.score-metrics b{font-size:14px}.score-actions{display:grid;gap:7px}.score-actions :deep(button){min-height:42px;padding:0 14px;border:1px solid #4a5046;display:flex;align-items:center;justify-content:center;gap:7px;background:transparent;color:var(--on-contrast);font:700 10px 'DM Mono';cursor:pointer}.score-actions :deep(button.primary){border-color:var(--sport,var(--accent));background:var(--sport,var(--accent));color:var(--contrast)}.score-actions :deep(button:disabled){opacity:.4;cursor:not-allowed}@media(max-width:1100px){.unified-builder-score{grid-template-columns:auto 1fr}.score-metrics,.score-actions{grid-column:2}.score-actions{grid-template-columns:1fr 1fr}}@media(max-width:700px){.unified-builder-score{grid-template-columns:1fr;text-align:center}.score-ring{margin:auto}.score-metrics,.score-actions{grid-column:1}.score-copy p{margin:auto}}
</style>
