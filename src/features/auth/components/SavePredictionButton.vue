<script setup>
import { onMounted, ref } from 'vue'
import { BookmarkPlus, Check } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { api } from '../../../services/api'
import { useAuthStore } from '../stores/auth'
import AuthModal from './AuthModal.vue'

const props=defineProps({prediction:{type:Object,required:true}})
const auth=useAuthStore(),route=useRoute(),prompt=ref(false),saving=ref(false),saved=ref(false),error=ref('')
const storageKey='ninth:pending-prediction'
const save=async()=>{if(saving.value||saved.value)return;saving.value=true;error.value='';try{await api.savedCreate('predictions',props.prediction);saved.value=true;sessionStorage.removeItem(storageKey)}catch(failure){error.value=failure.message}finally{saving.value=false}}
const click=()=>{if(auth.isAuthenticated)return save();sessionStorage.setItem(storageKey,JSON.stringify({path:route.fullPath,prediction:props.prediction}));prompt.value=true}
onMounted(()=>{if(!auth.isAuthenticated)return;try{const pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(pending?.path===route.fullPath&&pending?.prediction)save()}catch{sessionStorage.removeItem(storageKey)}})
</script>
<template><div class="save-prediction"><button type="button" :class="{saved}" :disabled="saving||saved" @click="click"><Check v-if="saved"/><BookmarkPlus v-else/><span>{{saved?'Prediction saved':saving?'Saving…':'Save prediction'}}</span></button><small v-if="error">{{error}}</small><AuthModal :open="prompt" title="Save this model read" copy="Sign in or create an account to preserve this exact prediction, probability and model version." @close="prompt=false"/></div></template>
<style scoped>.save-prediction{margin-top:14px;display:grid;gap:6px}.save-prediction>button{min-height:44px;padding:0 13px;display:flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--line);background:var(--surface);color:var(--text);font:700 10px 'DM Mono';cursor:pointer}.save-prediction>button:hover:not(:disabled){border-color:var(--accent)}.save-prediction>button.saved{border-color:rgba(214,255,97,.4);color:var(--accent)}.save-prediction svg{width:16px}.save-prediction small{color:var(--red);font-size:10px;text-align:center}</style>
