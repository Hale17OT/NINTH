<script setup>
import { motion, useReducedMotion } from 'motion-v'
import { motionEase } from '../../motion/system'
defineProps({ panelKey: { type: [String, Number], required: true } })
const reduced = useReducedMotion()
</script>
<template>
  <motion.div layout class="transition-panel" :transition="{layout:{duration:.42,ease:motionEase}}">
    <motion.div :key="panelKey" :initial="reduced?false:{opacity:0,y:10,filter:'blur(6px)'}" :animate="{opacity:1,y:0,filter:'blur(0px)'}" :transition="{duration:.38,ease:motionEase}"><slot/></motion.div>
  </motion.div>
</template>
