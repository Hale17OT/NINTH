<script setup>
import { RefreshCw } from "lucide-vue-next";
defineProps({ loading: Boolean });
defineEmits(["refresh"]);
</script>

<template>
  <div class="refresh-control"><span>DATA</span><button type="button" :disabled="loading" @click="$emit('refresh')"><RefreshCw :class="{ spin: loading }" /> REFRESH</button></div>
</template>

<style scoped>
.refresh-control{width:110px;min-width:110px}.refresh-control>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}button{width:110px;height:44px;padding:0 13px;border:1px solid var(--ink);background:var(--ink);color:var(--paper);display:flex;align-items:center;justify-content:center;gap:8px;font:700 8px 'DM Mono';cursor:pointer}button:hover:not(:disabled){background:var(--selection-bg);border-color:var(--accent);color:var(--selection-text)}button:disabled{opacity:.55;cursor:wait}svg{width:14px}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
