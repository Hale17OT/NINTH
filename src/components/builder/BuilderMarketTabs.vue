<script setup>
defineProps({ active: { type: String, required: true } });
const tabs = [
  { value: "moneyline", label: "MONEYLINE", to: "/builder?market=moneyline" },
  { value: "totals", label: "TOTALS", to: "/builder?market=totals" },
  { value: "combined", label: "MIXED", to: "/builder?market=combined" },
  { value: "props", label: "PLAYER PROPS", to: "/props-builder" },
];
</script>

<template>
  <div class="market-tabs"><span>MODEL</span><div><RouterLink v-for="tab in tabs" :key="tab.value" :to="tab.to" :class="{ active: active === tab.value }">{{ tab.label }}</RouterLink></div></div>
</template>

<style scoped>
.market-tabs>span{display:block;margin-bottom:7px;font:600 7px 'DM Mono';letter-spacing:.12em;color:var(--muted)}.market-tabs>div{display:flex;padding:4px;border:1px solid var(--line);background:var(--surface-2)}.market-tabs a{min-height:38px;display:grid;place-items:center;padding:0 14px;color:var(--muted);font-size:10px;font-weight:900;text-decoration:none;white-space:nowrap}.market-tabs a:hover{color:var(--text);background:var(--wash)}.market-tabs a.active{background:var(--selection-bg);color:var(--selection-text)}
@media(max-width:620px){.market-tabs>div{display:grid;grid-template-columns:1fr 1fr}.market-tabs a{padding:0 10px}}
</style>
