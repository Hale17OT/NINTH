<script setup>
import { motion, useReducedMotion } from "motion-v";
import SharedIndicator from "../motion/SharedIndicator.vue";
defineProps({ active: { type: String, required: true } });
const reduced = useReducedMotion();
const tabs = [
  { value: "moneyline", label: "MONEYLINE", to: "/builder?market=moneyline" },
  { value: "totals", label: "TOTALS", to: "/builder?market=totals" },
  { value: "combined", label: "MIXED", to: "/builder?market=combined" },
  { value: "props", label: "PLAYER PROPS", to: "/props-builder" },
];
</script>

<template>
  <div class="market-tabs">
    <span>MODEL</span>
    <div>
      <motion.div
        v-for="tab in tabs"
        :key="tab.value"
        class="tab-shell"
        :while-hover="reduced ? undefined : { y: -1 }"
        :while-press="reduced ? undefined : { scale: 0.98 }"
        ><RouterLink :to="tab.to" :class="{ active: active === tab.value }"
          >{{ tab.label
          }}<SharedIndicator
            v-if="active === tab.value"
            layout-id="builder-market-indicator" /></RouterLink
      ></motion.div>
    </div>
  </div>
</template>

<style scoped>
.market-tabs > span {
  display: block;
  margin-bottom: 8px;
  font: 700 11px "DM Mono";
  letter-spacing: 0.08em;
  color: var(--muted);
}
.market-tabs > div {
  display: flex;
  padding: 4px;
  border: 1px solid var(--line);
  background: var(--surface-2);
}
.tab-shell {
  flex: 1;
  min-width: 0;
}
.market-tabs a {
  position: relative;
  min-height: 48px;
  display: grid;
  place-items: center;
  padding: 0 14px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
  white-space: nowrap;
}
.market-tabs a:hover {
  color: var(--text);
  background: var(--wash);
}
.market-tabs a.active {
  background: var(--selection-bg);
  color: var(--selection-text);
}
@media (max-width: 620px) {
  .market-tabs > div {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .market-tabs a {
    padding: 0 10px;
  }
}
</style>
