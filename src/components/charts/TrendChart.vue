<script setup>
import { computed } from 'vue'
import AnalyticsChart from './AnalyticsChart.vue'
const props=defineProps({values:{type:Array,default:()=>[]},labels:{type:Array,default:()=>[]},pink:Boolean,type:{type:String,default:'line'},unit:{type:String,default:''},height:{type:Number,default:190}})
const chartLabels=computed(()=>props.labels.length===props.values.length?props.labels:props.values.map((_,index)=>props.type==='line'?(index?`Inn ${index}`:'Start'):String(index+1)))
const color=computed(()=>props.pink?'#ff7168':'#ff4d12')
</script>
<template><AnalyticsChart :labels="chartLabels" :series="[{label:unit||'Value',values,color,fill:type==='line'}]" :type="type" :unit="unit" :height="height" :begin-at-zero="type==='bar'"/></template>
