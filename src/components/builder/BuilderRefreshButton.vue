<script setup>
import { RefreshCw } from "lucide-vue-next";
import { motion, useReducedMotion } from "motion-v";
defineProps({ loading: Boolean });
defineEmits(["refresh"]);
const reduced = useReducedMotion();
</script>

<template>
  <div class="refresh-control">
    <span>DATA</span
    ><motion.button
      type="button"
      :disabled="loading"
      :while-hover="reduced ? undefined : { y: -2 }"
      :while-press="reduced ? undefined : { scale: 0.97 }"
      @click="$emit('refresh')"
      ><RefreshCw :class="{ spin: loading }" /> REFRESH</motion.button
    >
  </div>
</template>

<style scoped>
.refresh-control {
  width: 100%;
  min-width: 0;
}
.refresh-control > span {
  display: block;
  margin-bottom: 8px;
  font: 700 11px "DM Mono";
  letter-spacing: 0.08em;
  color: var(--muted);
  text-transform: uppercase;
}
button {
  width: 100%;
  height: 48px;
  padding: 0 13px;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: var(--paper);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font: 700 11px "DM Mono";
  cursor: pointer;
}
button:hover:not(:disabled) {
  background: var(--selection-bg);
  border-color: var(--accent);
  color: var(--selection-text);
}
button:disabled {
  opacity: 0.55;
  cursor: wait;
}
svg {
  width: 14px;
}
.spin {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
