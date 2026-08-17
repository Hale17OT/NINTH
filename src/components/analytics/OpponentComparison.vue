<script setup>import SplitComparison from './SplitComparison.vue';defineProps({rows:{type:Array,default:()=>[]},title:{type:String,default:'Opponent context'}})</script>
<template><SplitComparison :rows="rows" :title="title"/></template>
