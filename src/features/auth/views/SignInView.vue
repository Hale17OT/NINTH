<script setup>
import { reactive, ref } from 'vue'
import { Eye, EyeOff } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import GoogleSignInButton from '../components/GoogleSignInButton.vue'
import { useAuthStore } from '../stores/auth'
import { safeReturnTo } from '../composables/access'

const auth = useAuthStore(), route = useRoute(), router = useRouter()
const form = reactive({ email: '', password: '', remember: true }), showPassword = ref(false), error = ref(''), fields = ref({})
const returnTo = () => safeReturnTo(route.query.returnTo)
const submit = async () => {
  error.value = ''; fields.value = {}
  try { await auth.login(form); router.replace(returnTo()) }
  catch (failure) { error.value = failure.message; fields.value = failure.fields || {} }
}
const google = async () => { error.value = ''; try { await auth.loginWithGoogle(returnTo(), form.remember) } catch (failure) { error.value = failure.message } }
</script>
<template><AuthShell eyebrow="NINTH / SIGN IN" step="01" story-title="Return to your decision system." story-copy="Your saved cards, model snapshots and account preferences stay attached to one secure analytical workspace.">
  <div class="auth-form"><header class="auth-form-head"><span>WELCOME BACK</span><h2>Continue where you left off.</h2><p>Sign in to open advanced builders and your saved intelligence.</p></header>
    <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
    <form novalidate @submit.prevent="submit">
      <label class="auth-field"><span>Email</span><input v-model.trim="form.email" type="email" autocomplete="email" placeholder="you@example.com" :aria-invalid="Boolean(fields.email)" required><small v-if="fields.email">{{fields.email}}</small></label>
      <label class="auth-field"><span>Password</span><div class="password-wrap"><input v-model="form.password" :type="showPassword?'text':'password'" autocomplete="current-password" placeholder="Your password" :aria-invalid="Boolean(fields.password)" required><button type="button" :aria-label="showPassword?'Hide password':'Show password'" @click="showPassword=!showPassword"><EyeOff v-if="showPassword"/><Eye v-else/></button></div><small v-if="fields.password">{{fields.password}}</small></label>
      <div class="auth-row"><label class="auth-check"><input v-model="form.remember" type="checkbox"><span>Remember me</span></label><RouterLink class="auth-link" :to="{path:'/auth/forgot-password',query:{returnTo:returnTo()}}">Forgot password?</RouterLink></div>
      <button class="auth-submit" type="submit" :disabled="auth.loading">{{ auth.loading?'Signing in…':'Sign in' }}</button>
    </form>
    <div class="auth-divider">or continue with</div><GoogleSignInButton :loading="auth.loading" :disabled="!auth.config.googleConfigured" @click="google"/><small v-if="!auth.config.googleConfigured" class="google-unavailable">Google Sign-In becomes available after the OAuth client is connected.</small>
    <p class="auth-switch">New to NINTH?<RouterLink :to="{path:'/auth/sign-up',query:{returnTo:returnTo()}}">Create an account</RouterLink></p>
  </div>
</AuthShell></template>
