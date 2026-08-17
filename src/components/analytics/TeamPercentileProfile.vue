<script setup>import PlayerPercentileProfile from './PlayerPercentileProfile.vue';defineProps({metrics:{type:Array,default:()=>[]},sample:{type:Number,default:0},title:{type:String,default:'League position'}})</script>
<template><PlayerPercentileProfile :metrics="metrics" :sample="sample" :title="title"/></template>
