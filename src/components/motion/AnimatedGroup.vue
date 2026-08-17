<script setup>
import { motion, useReducedMotion } from 'motion-v'
import { motionEase } from '../../motion/system'
defineProps({ as: { type: String, default: 'div' }, delay: { type: Number, default: 0 }, amount: { type: Number, default: .12 } })
const reduced = useReducedMotion()
</script>

<template>
  <motion.div
    :as="as"
    :initial="reduced ? false : 'hidden'"
    :whileInView="'shown'"
    :inViewOptions="{ once: true, amount }"
    :variants="{ hidden:{}, shown:{ transition:{ delayChildren:delay, staggerChildren:.08 } } }"
  ><slot :item="{ variants:{ hidden:{opacity:0,y:22,filter:'blur(8px)'}, shown:{opacity:1,y:0,filter:'blur(0px)',transition:{duration:.56,ease:motionEase}} } }" /></motion.div>
</template>
