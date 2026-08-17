<script setup>
import { motion } from 'motion-v'
defineProps({ layoutId: { type: String, default: 'active-indicator' } })
</script>
<template><motion.span class="shared-indicator" :layout-id="layoutId" :transition="{ type: 'spring', stiffness: 430, damping: 38 }" aria-hidden="true"/></template>
<style scoped>.shared-indicator{position:absolute;inset:auto 8px 5px;height:2px;background:var(--workspace-accent,var(--accent));border-radius:999px}</style>
