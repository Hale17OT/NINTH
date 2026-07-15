<script setup>
import { computed } from 'vue'
import { Bar, Line } from 'vue-chartjs'
import { Chart as ChartJS, BarElement, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip } from 'chart.js'
import { useAppStore } from '../../stores/app'
ChartJS.register(BarElement,CategoryScale,LinearScale,PointElement,LineElement,Filler,Tooltip)

const store=useAppStore()
const props=defineProps({values:{type:Array,default:()=>[]},labels:{type:Array,default:()=>[]},pink:Boolean,type:{type:String,default:'line'},unit:{type:String,default:''}})
const labels=computed(()=>props.labels.length===props.values.length?props.labels:props.values.map((_,index)=>props.type==='line'?(index?`Inn ${index}`:'Start'):String(index+1)))
const dark=computed(()=>store.theme==='dark')
const data=computed(()=>({labels:labels.value,datasets:[{data:props.values,borderColor:props.pink?'#ff7258':dark.value?'#b9ed39':'#171b16',backgroundColor:props.pink?'rgba(255,114,88,.72)':'rgba(185,237,57,.68)',fill:props.type==='line',tension:.28,pointRadius:props.type==='line'?3:0,pointHoverRadius:5,borderWidth:2,borderRadius:props.type==='bar'?2:0}]}))
const options=computed(()=>({responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},plugins:{legend:{display:false},tooltip:{enabled:true,displayColors:false,callbacks:{label:context=>`${context.raw}${props.unit?` ${props.unit}`:''}`}}},scales:{x:{display:true,grid:{display:false},ticks:{color:dark.value?'#a0a79d':'#73786f',font:{size:8,family:'DM Mono'},maxRotation:0,autoSkip:props.values.length>12}},y:{display:true,beginAtZero:props.type==='bar',grid:{color:dark.value?'rgba(242,241,233,.1)':'rgba(30,32,28,.08)'},ticks:{color:dark.value?'#a0a79d':'#73786f',font:{size:8,family:'DM Mono'},precision:0}}}}))
</script>
<template><div class="chart"><Bar v-if="type==='bar'" :data="data" :options="options"/><Line v-else :data="data" :options="options"/></div></template>
<style scoped>.chart{height:190px}</style>
