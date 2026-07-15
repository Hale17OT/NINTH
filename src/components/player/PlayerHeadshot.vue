<script setup>
import { computed, ref, watch } from 'vue'
const props=defineProps({player:{type:Object,default:()=>({})},id:[String,Number],name:String,size:{type:[String,Number],default:72}})
const failed=ref(false)
const playerId=computed(()=>props.id||props.player?.id||props.player?.playerId)
const playerName=computed(()=>props.name||props.player?.name||props.player?.fullName||'MLB Player')
const initials=computed(()=>playerName.value.split(' ').map(part=>part[0]).join('').slice(0,2))
const src=computed(()=>playerId.value?`https://img.mlbstatic.com/mlb-photos/image/upload/c_fit,w_426,h_640,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/${playerId.value}/headshot/67/current`:'')
const style=computed(()=>({width:`${props.size}px`,height:`${props.size}px`}))
watch(src,()=>{failed.value=false})
</script>
<template><span class="headshot" :style="style"><template v-if="src&&!failed"><img class="backdrop" :src="src" alt="" aria-hidden="true"><img class="portrait-image" :src="src" :alt="`${playerName} headshot`" loading="lazy" @error="failed=true"></template><b v-else>{{initials}}</b></span></template>
<style scoped>.headshot{position:relative;display:inline-grid;place-items:center;flex:none;overflow:hidden;border-radius:8px;border:1px solid var(--line);background:var(--wash)}.headshot img{position:absolute;inset:0;width:100%;height:100%}.backdrop{object-fit:cover;object-position:center top;filter:blur(12px) saturate(.65);transform:scale(1.12);opacity:.22}.portrait-image{object-fit:contain;object-position:center bottom;z-index:1}.headshot b{font:800 15px 'DM Mono';color:var(--acid)}</style>
