<script setup>
defineProps({ active: { type: Boolean, default: true } })
</script>
<template><span class="border-trail" :class="{ active }" aria-hidden="true"><i></i></span></template>
<style scoped>
.border-trail{position:absolute;inset:-1px;overflow:hidden;pointer-events:none;border-radius:inherit}.border-trail i{position:absolute;left:-28%;top:0;width:28%;height:1px;background:linear-gradient(90deg,transparent,var(--workspace-accent,var(--accent)),transparent);filter:drop-shadow(0 0 5px var(--workspace-accent,var(--accent)));opacity:0}.border-trail.active i{opacity:1;animation:trail-x 3.1s linear infinite}@keyframes trail-x{to{left:102%}}@media(prefers-reduced-motion:reduce){.border-trail i{display:none}}
</style>
