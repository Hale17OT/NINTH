<script setup>
import { computed, ref, watch } from 'vue'
import AnalyticsChart from '../charts/AnalyticsChart.vue'
const props=defineProps({labels:{type:Array,default:()=>[]},series:{type:Array,default:()=>[]},title:{type:String,default:'Performance trajectory'},unit:{type:String,default:''},height:{type:Number,default:320}})
const windowSize=ref('all');watch(()=>props.labels.length,()=>windowSize.value='all')
const count=computed(()=>windowSize.value==='all'?props.labels.length:Number(windowSize.value))
const labels=computed(()=>props.labels.slice(-count.value))
const series=computed(()=>props.series.map(row=>({...row,values:(row.values||[]).slice(-count.value)})))
</script>
<template><section class="rolling-trend"><header><div><span class="eyebrow">ROLLING TREND</span><h2>{{title}}</h2></div><nav v-if="labels.length>5"><button v-for="range in [{v:'5',l:'L5'},{v:'10',l:'L10'},{v:'all',l:'ALL'}]" :key="range.v" :class="{active:windowSize===range.v}" @click="windowSize=range.v">{{range.l}}</button></nav></header><AnalyticsChart :labels="labels" :series="series" :unit="unit" :height="height"/><slot/></section></template>
<style scoped>.rolling-trend{padding:20px;border:1px solid var(--line);background:var(--surface)}header{display:flex;align-items:end;justify-content:space-between;gap:18px;margin-bottom:14px}h2{margin:5px 0 0;font-size:27px;letter-spacing:-.045em}nav{display:flex;border:1px solid var(--line);padding:3px}button{min-width:42px;height:29px;border:0;background:transparent;color:var(--muted);font:800 7px 'DM Mono'}button.active{background:var(--selection-bg);color:var(--selection-text)}</style>
