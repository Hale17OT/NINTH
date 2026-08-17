<script setup>
import { RefreshCw, WifiOff } from 'lucide-vue-next'

defineProps({ message: { type: String, default: 'Official data could not be loaded.' } })
defineEmits(['retry'])
</script>

<template>
  <section class="load-error" role="alert">
    <WifiOff :size="22"/>
    <div><span>CONNECTION INTERRUPTED</span><h3>This screen stopped waiting.</h3><p>{{ message }}</p></div>
    <button type="button" @click="$emit('retry')"><RefreshCw :size="14"/> TRY AGAIN</button>
  </section>
</template>

<style scoped>
.load-error{min-height:150px;padding:24px;border:1px solid color-mix(in srgb,var(--orange) 45%,var(--line));background:color-mix(in srgb,var(--orange) 5%,var(--surface));display:grid;grid-template-columns:44px 1fr auto;align-items:center;gap:17px}.load-error>svg{width:44px;height:44px;padding:10px;border:1px solid var(--line);color:var(--orange)}span{font:700 7px 'DM Mono';letter-spacing:.12em;color:var(--orange)}h3{font-size:16px;margin:6px 0 0}p{margin:5px 0 0;font-size:9px;line-height:1.5;color:var(--muted)}button{height:40px;padding:0 14px;border:0;background:var(--ink);color:var(--paper);display:flex;align-items:center;gap:7px;font:700 8px 'DM Mono';cursor:pointer}@media(max-width:600px){.load-error{grid-template-columns:44px 1fr}.load-error button{grid-column:2;justify-self:start}}
.load-error{border-color:color-mix(in srgb,var(--red) 45%,var(--line));border-radius:var(--radius-sm);background:color-mix(in srgb,var(--red) 5%,var(--surface))}.load-error>svg,.load-error span{color:var(--red)}.load-error button{background:var(--red);color:#fff}
</style>
