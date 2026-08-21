<script setup>
import { ref } from 'vue'
import AuthShell from '../components/AuthShell.vue'
import { api } from '../../../services/api'
const email=ref(''),loading=ref(false),error=ref(''),sent=ref(false)
const submit=async()=>{loading.value=true;error.value='';try{await api.authForgotPassword(email.value);sent.value=true}catch(failure){error.value=failure.message}finally{loading.value=false}}
</script>
<template><AuthShell eyebrow="NINTH / RECOVERY" step="03" story-title="Secure recovery, without losing your work." story-copy="Reset links are short-lived, single-use and stored only as hashes inside the account database."><div class="auth-form"><header class="auth-form-head"><span>PASSWORD RECOVERY</span><h2>Find your way back.</h2><p>Enter the email attached to your account. We’ll send a secure reset link if it exists.</p></header><div v-if="sent" class="auth-status"><div class="auth-success">If an account exists for this email, we've sent password reset instructions.</div><RouterLink class="auth-submit" to="/auth/sign-in">Return to sign in</RouterLink></div><template v-else><p v-if="error" class="auth-error">{{error}}</p><form @submit.prevent="submit"><label class="auth-field"><span>Email</span><input v-model.trim="email" type="email" autocomplete="email" placeholder="you@example.com" required></label><button class="auth-submit" :disabled="loading">{{loading?'Sending reset link…':'Send reset link'}}</button></form><p class="auth-switch">Remembered it?<RouterLink to="/auth/sign-in">Sign in</RouterLink></p></template></div></AuthShell></template>
