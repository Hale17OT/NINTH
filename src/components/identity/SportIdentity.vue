<script setup>
import { computed, ref, watch } from 'vue'
import { identityInitials, resolveTeamIdentity } from '../../domain/sports'
const props = defineProps({ identity: { type: Object, default: () => ({}) }, size: { type: Number, default: 54 }, square: Boolean })
const failed = ref(false)
const resolved = computed(() => resolveTeamIdentity(props.identity))
const source = computed(() => failed.value ? null : resolved.value.badge || props.identity?.image || null)
const fail = event => {
  failed.value = true
  event?.currentTarget?.removeAttribute('src')
}
watch(() => [props.identity?.id, props.identity?.badge, props.identity?.logo, props.identity?.image], () => { failed.value = false })
</script>
<template><span class="sport-identity" :class="{square,fallback:!source}" :data-identity-key="resolved.canonicalKey" :style="{width:`${size}px`,height:`${size}px`}"><img v-if="source" :src="source" :alt="`${identity.name || 'Entity'} identity`" loading="lazy" @error="fail"><b v-else :aria-label="`${identity.name||'Entity'} monogram fallback`">{{ identityInitials(identity) }}</b></span></template>
<style scoped>.sport-identity{flex:none;display:grid;place-items:center;overflow:hidden;border:1px solid var(--line);border-radius:50%;background:color-mix(in srgb,var(--sport,var(--accent)) 8%,var(--surface))}.sport-identity.square{border-radius:12px}.sport-identity img{width:78%;height:78%;object-fit:contain}.sport-identity.fallback{background:repeating-linear-gradient(135deg,color-mix(in srgb,var(--sport,var(--accent)) 9%,var(--surface)) 0 8px,var(--surface) 8px 16px)}.sport-identity b{max-width:90%;font:800 clamp(8px,1vw,13px) 'DM Mono';letter-spacing:-.04em;color:var(--sport,var(--accent));text-align:center}</style>
