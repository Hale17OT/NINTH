<script setup>
defineProps({ as: { type: String, default: 'article' }, tone: { type: String, default: 'default' }, interactive: Boolean })
</script>
<template><component :is="as" class="ninth-card motion-surface" :class="[`tone-${tone}`,{interactive}]"><slot/></component></template>
<style scoped>.ninth-card{position:relative;overflow:hidden}.interactive:hover{transform:translateY(-3px)}.tone-contrast{background:var(--contrast);color:var(--on-contrast)}.tone-accent{background:var(--accent);color:#071005}.tone-signal{border-color:color-mix(in srgb,var(--green) 45%,var(--line))}</style>
