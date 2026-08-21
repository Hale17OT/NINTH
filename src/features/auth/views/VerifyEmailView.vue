<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertCircle, CheckCircle2, LoaderCircle } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import { api } from '../../../services/api'
import { useAuthStore } from '../stores/auth'
const route=useRoute(),auth=useAuthStore(),state=ref('loading'),message=ref('Verifying your email…'),token=computed(()=>String(route.query.token||''))
onMounted(async()=>{if(!token.value){state.value='error';message.value='This verification link is incomplete.';return}try{const result=await api.authVerifyEmail(token.value);auth.setUser(result.user);state.value='success';message.value=result.message}catch(error){state.value='error';message.value=error.message}})
</script>
<template><AuthShell eyebrow="NINTH / EMAIL VERIFICATION" step="05" story-title="One verified identity. Every saved decision." story-copy="Verification prevents someone else from attaching builders and account recovery to an address they do not control."><div class="auth-form auth-status"><div class="status-mark"><LoaderCircle v-if="state==='loading'" class="spin"/><CheckCircle2 v-else-if="state==='success'"/><AlertCircle v-else/></div><h2>{{state==='loading'?'Confirming identity':state==='success'?'Email verified':'Link unavailable'}}</h2><p>{{message}}</p><RouterLink v-if="state!=='loading'" class="auth-submit" :to="state==='success'?'/account':'/auth/sign-in'">{{state==='success'?'Open account':'Return to sign in'}}</RouterLink></div></AuthShell></template>
<style scoped>.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style>
