<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from './components/layout/AppLayout.vue'
import { useAppStore } from './stores/app'

const store = useAppStore()
const route = useRoute()
const isBaseball = computed(() => route.meta?.sport === 'baseball')
let dashboardTimer

onMounted(() => {
  if (isBaseball.value) store.load()
  dashboardTimer = window.setInterval(() => { if (isBaseball.value) store.load(true) }, 30_000)
})
watch(isBaseball, active => { if (active) store.load() })
onBeforeUnmount(() => window.clearInterval(dashboardTimer))
</script>

<template>
  <AppLayout>
    <div v-if="isBaseball && store.error" class="provider-error panel">
      <span>OFFICIAL DATA PROVIDER UNAVAILABLE</span>
      <p>{{ store.error }}</p>
      <button @click="store.load(true)">RETRY CONNECTION</button>
    </div>
    <div v-if="isBaseball && store.syncError" class="sync-warning">
      <span>LIVE FEED RETRYING · CURRENT PAGE REMAINS AVAILABLE</span>
      <button @click="store.load(true)">RETRY NOW</button>
    </div>
    <RouterView v-slot="{ Component }">
      <Transition name="page">
        <component :is="Component" :key="$route.fullPath" />
      </Transition>
    </RouterView>
  </AppLayout>
</template>

<style>
.page-enter-active,.page-leave-active{transition:opacity .18s,transform .18s}.page-enter-from{opacity:0;transform:translateY(6px)}.page-leave-to{opacity:0}.provider-error{padding:20px;text-align:center;margin-top:12px}.provider-error span{font:700 11px 'DM Mono';color:var(--orange)}.provider-error p{font-size:12px;color:var(--muted)}.provider-error button{padding:9px 12px;background:var(--acid);border:0;border-radius:5px;font-size:10px;font-weight:800}.sync-warning{min-height:36px;margin-top:12px;padding:8px 11px;border:1px solid color-mix(in srgb,var(--orange) 45%,var(--line));background:color-mix(in srgb,var(--orange) 7%,var(--surface));display:flex;align-items:center;justify-content:space-between;gap:15px;color:var(--orange);font:700 7px 'DM Mono';letter-spacing:.06em}.sync-warning button{padding:7px 9px;border:0;background:var(--ink);color:var(--paper);font:700 7px 'DM Mono';cursor:pointer}
</style>
