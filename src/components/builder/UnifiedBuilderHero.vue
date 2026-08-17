<script setup>
import { motion, useReducedMotion } from 'motion-v'
import TextEffect from '../motion/TextEffect.vue'

defineProps({
  eyebrow: { type: String, required: true },
  title: { type: String, required: true },
  accent: { type: String, required: true },
  description: { type: String, required: true },
})
const reduced = useReducedMotion()
</script>

<template>
  <motion.section
    class="unified-builder-hero"
    :initial="reduced ? false : { opacity: 0, y: 18 }"
    :animate="{ opacity: 1, y: 0 }"
    :transition="{ duration: .52, ease: [.16, 1, .3, 1] }"
  >
    <div class="hero-copy">
      <motion.span class="eyebrow" :initial="reduced ? false : { opacity: 0, x: -10 }" :animate="{ opacity: 1, x: 0 }">{{ eyebrow }}</motion.span>
      <h1><TextEffect :text="title" :delay=".05"/><br><em><TextEffect :text="accent" :delay=".13"/></em></h1>
      <motion.p :initial="reduced ? false : { opacity: 0, y: 9 }" :animate="{ opacity: 1, y: 0 }" :transition="{ delay: .2 }">{{ description }}</motion.p>
    </div>
    <motion.div class="hero-tools" :initial="reduced ? false : { opacity: 0, x: 18 }" :animate="{ opacity: 1, x: 0 }" :transition="{ delay: .12, duration: .48 }">
      <slot />
    </motion.div>
  </motion.section>
</template>

<style scoped>
.unified-builder-hero{min-height:290px;padding:36px;display:flex;align-items:flex-end;justify-content:space-between;gap:28px;overflow:visible;border:1px solid var(--line);background:radial-gradient(circle at 80% 15%,color-mix(in srgb,var(--sport,var(--accent)) 34%,transparent),transparent 31%),var(--surface)}.hero-copy{min-width:0}.hero-copy h1{margin:14px 0 20px;font-size:clamp(45px,6vw,82px);line-height:.86;letter-spacing:-.075em}.hero-copy h1 em{font-style:normal;color:var(--sport,var(--accent))}.hero-copy p{max-width:640px;margin:0;color:var(--muted);font-size:13px;line-height:1.65}.hero-tools{width:min(840px,58vw);max-width:100%;min-width:0;display:grid;justify-items:stretch;gap:14px}@media(max-width:1200px){.unified-builder-hero{align-items:flex-start;flex-direction:column}.hero-tools{width:100%}}@media(max-width:700px){.unified-builder-hero{min-height:0;padding:25px}.hero-copy h1{font-size:clamp(43px,14vw,64px)}.hero-tools{width:100%}}
</style>
