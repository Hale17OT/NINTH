<script setup>
import { computed } from 'vue'

const props = defineProps({
  sport: { type: String, default: 'baseball' },
  accent: { type: String, default: '#d6ff61' },
  compact: { type: Boolean, default: false },
})

const asset = computed(() => `/media/sports/${props.sport}-hero.png`)
</script>

<template>
  <div class="sport-visual" :class="{ compact }" :style="{ '--visual-accent': accent }" aria-hidden="true">
    <span class="visual-glow"></span>
    <span class="orbit orbit-a"></span>
    <span class="orbit orbit-b"></span>
    <span class="coordinate coordinate-x"></span>
    <span class="coordinate coordinate-y"></span>
    <img :src="asset" alt="" decoding="async" fetchpriority="high">
    <span class="object-shadow"></span>
    <span class="tracking-chip mono">OBJ / {{ sport.toUpperCase() }}</span>
  </div>
</template>

<style scoped>
.sport-visual {
  position: relative;
  width: min(47vw, 680px);
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  isolation: isolate;
  perspective: 900px;
}
.sport-visual img {
  position: relative;
  z-index: 4;
  width: 87%;
  height: 87%;
  object-fit: contain;
  transform: rotate(-7deg) translate3d(0, -1%, 38px);
  filter: drop-shadow(0 38px 34px rgba(0,0,0,.58));
}
.visual-glow {
  position: absolute;
  z-index: 0;
  inset: 19%;
  border-radius: 50%;
  background: var(--visual-accent);
  filter: blur(78px);
  opacity: .16;
}
.orbit {
  position: absolute;
  z-index: 1;
  border: 1px solid color-mix(in srgb, var(--visual-accent) 30%, transparent);
  border-radius: 50%;
  transform: rotate(-17deg);
}
.orbit-a { inset: 2%; }
.orbit-b { inset: 13%; border-style: dashed; opacity: .7; }
.coordinate { position: absolute; z-index: 1; background: color-mix(in srgb, var(--visual-accent) 20%, transparent); }
.coordinate-x { left: 0; right: 0; top: 50%; height: 1px; }
.coordinate-y { top: 0; bottom: 0; left: 50%; width: 1px; }
.object-shadow {
  position: absolute;
  z-index: 2;
  left: 20%; right: 12%; bottom: 10%; height: 12%;
  border-radius: 50%;
  background: rgba(0,0,0,.72);
  filter: blur(24px);
  transform: rotate(-8deg);
}
.tracking-chip {
  position: absolute;
  z-index: 5;
  right: 5%;
  bottom: 14%;
  padding: 7px 9px;
  border: 1px solid color-mix(in srgb, var(--visual-accent) 38%, transparent);
  background: rgba(4,7,5,.72);
  color: var(--visual-accent);
  font-size: 12px;
  letter-spacing: .08em;
  backdrop-filter: blur(12px);
}
.compact { width: min(36vw, 480px); }
@media (max-width: 900px) { .sport-visual { width: min(75vw, 610px); } }
@media (max-width: 640px) {
  .sport-visual { width: min(108vw, 520px); }
  .tracking-chip { display: none; }
}
@media (prefers-reduced-motion: no-preference) {
  .orbit-a { animation: orbit-turn 24s linear infinite; }
  .orbit-b { animation: orbit-turn 17s linear infinite reverse; }
  .sport-visual img { animation: object-float 6s ease-in-out infinite; }
}
@keyframes orbit-turn { to { transform: rotate(343deg); } }
@keyframes object-float {
  0%, 100% { transform: rotate(-7deg) translate3d(0,-1%,38px); }
  50% { transform: rotate(-4deg) translate3d(0,-4%,50px); }
}
</style>
