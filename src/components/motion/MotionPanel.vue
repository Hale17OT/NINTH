<script setup>
import { motion, useReducedMotion } from 'motion-v'

defineProps({
  as: { type: String, default: 'div' },
  delay: { type: Number, default: 0 },
  lift: { type: Number, default: 14 },
  inView: { type: Boolean, default: true },
})

const reduced = useReducedMotion()
</script>

<template>
  <motion.div
    :as="as"
    :initial="reduced ? false : { opacity: 0, y: lift }"
    :whileInView="inView && !reduced ? { opacity: 1, y: 0 } : undefined"
    :animate="!inView && !reduced ? { opacity: 1, y: 0 } : undefined"
    :inViewOptions="{ once: true, amount: .12 }"
    :transition="{ duration: .46, delay, ease: [.16, 1, .3, 1] }"
  ><slot /></motion.div>
</template>
