<script setup>
defineProps({ state: { type: String, default: 'neutral' }, label: { type: String, default: '' } })
</script>
<template><span class="evidence-badge" :class="`state-${state}`"><i></i><slot>{{ label }}</slot></span></template>
<style scoped>.evidence-badge{display:inline-flex;align-items:center;gap:8px;width:max-content;color:var(--muted);font:600 12px 'DM Mono';letter-spacing:.07em;line-height:1.4;text-transform:uppercase}.evidence-badge i{width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 12px color-mix(in srgb,currentColor 46%,transparent)}.state-ready,.state-positive{color:var(--green)}.state-live{color:var(--red)}.state-warning{color:var(--amber)}.state-brand{color:var(--accent)}</style>
