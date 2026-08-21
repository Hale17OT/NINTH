<script setup>
import { onMounted, ref } from 'vue'
import { AlertCircle, LoaderCircle } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import { useAuthStore } from '../stores/auth'
import { safeReturnTo } from '../composables/access'
import { trackAuthEvent } from '../services/authAnalytics'
const route=useRoute(),router=useRouter(),auth=useAuthStore(),error=ref('')
onMounted(async()=>{if(route.query.status!=='success'){error.value=route.query.reason==='cancelled'?'Google Sign-In was cancelled.':'Google Sign-In could not be completed.';return}await auth.refreshUser();if(auth.isAuthenticated){trackAuthEvent('auth_google_completed');router.replace(safeReturnTo(route.query.returnTo))}else error.value='The account session could not be restored.'})
</script>
<template><AuthShell eyebrow="NINTH / GOOGLE SIGN-IN" step="06" story-title="Linking trusted identity to private intelligence." story-copy="Google confirms your identity; NINTH still creates and manages its own revocable server-side session."><div class="auth-form auth-status"><div class="status-mark"><AlertCircle v-if="error"/><LoaderCircle v-else class="spin"/></div><h2>{{error?'Sign-In interrupted':'Securing your session'}}</h2><p>{{error||'Google confirmed your identity. NINTH is restoring your workspace now.'}}</p><RouterLink v-if="error" class="auth-submit" to="/auth/sign-in">Try again</RouterLink></div></AuthShell></template>
<style scoped>.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style>
