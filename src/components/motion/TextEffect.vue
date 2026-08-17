<script setup>
import { computed } from 'vue'
import { motion, useReducedMotion } from 'motion-v'
import { motionEase } from '../../motion/system'

const props = defineProps({
  text: { type: String, required: true },
  as: { type: String, default: 'span' },
  delay: { type: Number, default: 0 },
  by: { type: String, default: 'words' },
})
const reduced = useReducedMotion()
const pieces = computed(() => props.by === 'chars' ? [...props.text] : props.text.split(/(\s+)/))
</script>

<template>
  <component :is="as" class="text-effect" :aria-label="text">
    <motion.span
      v-for="(piece, index) in pieces"
      :key="`${piece}-${index}`"
      aria-hidden="true"
      :class="{ space: /^\s+$/.test(piece) }"
      :initial="reduced ? false : { opacity: 0, y: '0.8em', filter: 'blur(7px)' }"
      :animate="{ opacity: 1, y: 0, filter: 'blur(0px)' }"
      :transition="{ duration: .58, delay: delay + index * .035, ease: motionEase }"
    >{{ piece }}</motion.span>
  </component>
</template>

<style scoped>
.text-effect>span{display:inline-block}.text-effect>span.space{white-space:pre}
</style>
