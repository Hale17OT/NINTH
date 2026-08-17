<script setup>
import { motion, useReducedMotion } from "motion-v";
import SharedIndicator from "../motion/SharedIndicator.vue";
defineProps({ modelValue: { type: String, required: true } });
defineEmits(["update:modelValue"]);
const reduced = useReducedMotion();
</script>

<template>
  <div class="slate-mode"><span>SLATE</span><div><motion.button type="button" :class="{ active: modelValue === 'daily' }" :while-press="reduced ? undefined : { scale: .97 }" @click="$emit('update:modelValue', 'daily')">DAILY<SharedIndicator v-if="modelValue === 'daily'" layout-id="slate-mode-indicator"/></motion.button><motion.button type="button" :class="{ active: modelValue === 'multi' }" :while-press="reduced ? undefined : { scale: .97 }" @click="$emit('update:modelValue', 'multi')">MULTI-DAY<SharedIndicator v-if="modelValue === 'multi'" layout-id="slate-mode-indicator"/></motion.button></div></div>
</template>

<style scoped>
.slate-mode{width:100%}.slate-mode>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.slate-mode>div{height:44px;display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);background:var(--surface);padding:3px}.slate-mode button{position:relative;border:0;background:transparent;font:700 7px 'DM Mono';letter-spacing:.04em;color:var(--muted);cursor:pointer}.slate-mode button:hover{color:var(--text);background:var(--wash)}.slate-mode button.active{background:var(--selection-bg);color:var(--selection-text)}
</style>
