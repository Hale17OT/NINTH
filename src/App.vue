<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion-v'
import AppLayout from './components/layout/AppLayout.vue'
import { useAppStore } from './stores/app'
import { createSharedPoller } from './services/polling'

const store = useAppStore()
const route = useRoute()
const isBaseball = computed(() => route.meta?.sport === 'baseball')
const reduced = useReducedMotion()
let dashboardPoller

onMounted(() => {
  dashboardPoller = createSharedPoller({
    key: 'dashboard',
    task: () => isBaseball.value ? store.load(true) : undefined,
    interval: () => !isBaseball.value ? 0 : store.dashboard?.live?.length ? 10_000 : 300_000,
  })
  dashboardPoller.start()
})
watch(isBaseball, active => { if (active) dashboardPoller?.trigger() })
onBeforeUnmount(() => dashboardPoller?.stop())
</script>

<template>
  <MotionConfig :transition="{ duration: .32, ease: [.16, 1, .3, 1] }" reduced-motion="user">
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
      <AnimatePresence mode="wait">
        <motion.div
          :key="$route.fullPath"
          class="route-stage"
          :initial="reduced ? false : { opacity: 0, y: 14, filter: 'blur(8px)', clipPath: 'inset(0 0 4% 0)' }"
          :animate="{ opacity: 1, y: 0, filter: 'blur(0px)', clipPath: 'inset(0 0 0% 0)' }"
          :exit="reduced ? undefined : { opacity: 0, y: -8, filter: 'blur(5px)' }"
          :transition="{ duration: .42, ease: [.16, 1, .3, 1] }"
        ><component :is="Component" /></motion.div>
      </AnimatePresence>
    </RouterView>
  </AppLayout>
  </MotionConfig>
</template>

<style>
.route-stage{min-width:0}.provider-error{padding:20px;text-align:center;margin-top:12px}.provider-error span{font:700 12px 'DM Mono';color:var(--red)}.provider-error p{font-size:13px;color:var(--muted)}.provider-error button{padding:9px 12px;background:var(--acid);border:0;border-radius:5px;font-size:12px;font-weight:800}.sync-warning{min-height:44px;margin-top:12px;padding:9px 12px;border:1px solid color-mix(in srgb,var(--amber) 45%,var(--line));background:color-mix(in srgb,var(--amber) 7%,var(--surface));display:flex;align-items:center;justify-content:space-between;gap:15px;color:var(--amber);font:700 11px 'DM Mono';letter-spacing:.05em}.sync-warning button{padding:8px 10px;border:0;background:var(--ink);color:var(--paper);font:700 11px 'DM Mono';cursor:pointer}
.provider-error{border-color:color-mix(in srgb,var(--red) 45%,var(--line));background:color-mix(in srgb,var(--red) 6%,var(--surface))}.provider-error span{color:var(--red)}.provider-error button{background:var(--red);color:#fff;border-radius:var(--radius-xs)}.sync-warning{border-color:color-mix(in srgb,var(--amber) 45%,var(--line));background:color-mix(in srgb,var(--amber) 7%,var(--surface));color:var(--amber)}
</style>
