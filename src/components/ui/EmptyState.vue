<script setup>
import { CalendarX2, SearchX, UserRoundX, ShieldX, Inbox, ListX } from 'lucide-vue-next'

const props = defineProps({
  kind: { type: String, default: 'empty' },
  eyebrow: { type: String, default: 'NOTHING FOUND' },
  title: { type: String, required: true },
  detail: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
  actionTo: { type: [String, Object], default: '' },
})

const icons = { games: CalendarX2, search: SearchX, players: UserRoundX, teams: ShieldX, list: ListX, empty: Inbox }
</script>

<template>
  <section class="empty-state" role="status">
    <div class="empty-mark"><component :is="icons[props.kind] || icons.empty" :size="24"/></div>
    <div>
      <span class="empty-eyebrow">{{ eyebrow }}</span>
      <h3>{{ title }}</h3>
      <p v-if="detail">{{ detail }}</p>
    </div>
    <RouterLink v-if="actionLabel && actionTo" :to="actionTo">{{ actionLabel }} <span>→</span></RouterLink>
  </section>
</template>

<style scoped>
.empty-state{min-height:150px;padding:25px;border:1px solid var(--line);background:linear-gradient(135deg,color-mix(in srgb,var(--wash) 72%,transparent),transparent),var(--surface);display:grid;grid-template-columns:50px minmax(0,1fr) auto;align-items:center;gap:18px}.empty-mark{width:50px;height:50px;display:grid;place-items:center;border:1px solid var(--line);background:var(--wash);color:var(--muted)}.empty-eyebrow{font:700 7px 'DM Mono';letter-spacing:.12em;color:var(--orange)}h3{font-size:17px;letter-spacing:-.025em;margin:6px 0 0}p{max-width:640px;margin:6px 0 0;color:var(--muted);font-size:9px;line-height:1.6}.empty-state>a{align-self:center;padding:11px 13px;background:var(--ink);color:var(--paper);text-decoration:none;font:700 8px 'DM Mono';letter-spacing:.05em}.empty-state>a span{margin-left:8px;color:var(--accent)}
@media(max-width:600px){.empty-state{grid-template-columns:42px 1fr;padding:19px}.empty-mark{width:42px;height:42px}.empty-state>a{grid-column:2;justify-self:start}}
</style>
