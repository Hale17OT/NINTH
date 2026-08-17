<script setup>
defineProps({ position: { type: String, default: 'bottom' }, height: { type: String, default: '90px' } })
</script>
<template><div class="progressive-blur" :class="position" :style="{height}" aria-hidden="true"><i v-for="n in 5" :key="n" :style="{'--n':n}"></i></div></template>
<style scoped>
.progressive-blur{position:absolute;z-index:8;left:0;right:0;bottom:0;pointer-events:none}.progressive-blur.top{top:0;bottom:auto;transform:rotate(180deg)}.progressive-blur i{position:absolute;inset:0;backdrop-filter:blur(calc(var(--n) * 2px));mask-image:linear-gradient(to bottom,transparent calc((var(--n) - 1) * 16%),#000 calc(var(--n) * 18%),transparent calc((var(--n) + 1) * 22%))}
</style>
