<script setup>
import { computed, reactive, ref } from 'vue'
import { Eye, EyeOff } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import GoogleSignInButton from '../components/GoogleSignInButton.vue'
import { useAuthStore } from '../stores/auth'
import { safeReturnTo } from '../composables/access'

const auth = useAuthStore(), route = useRoute(), router = useRouter()
const form = reactive({ displayName:'',email:'',password:'',passwordConfirmation:'',termsAccepted:false,remember:true }), showPassword = ref(false), error=ref(''), fields=ref({})
const checks = computed(() => [form.password.length>=10,/[A-Z]/.test(form.password),/[a-z]/.test(form.password),/[^A-Za-z0-9]/.test(form.password)])
const strength = computed(() => checks.value.filter(Boolean).length)
const returnTo = () => safeReturnTo(route.query.returnTo)
const submit=async()=>{error.value='';fields.value={};try{await auth.register(form);router.replace(returnTo())}catch(failure){error.value=failure.message;fields.value=failure.fields||{}}}
const google=async()=>{error.value='';try{await auth.loginWithGoogle(returnTo(),true)}catch(failure){error.value=failure.message}}
</script>
<template><AuthShell eyebrow="NINTH / CREATE ACCOUNT" step="02" story-title="Build a record of every sharp decision." story-copy="Move from one-off forecasts to a persistent intelligence ledger with secure ownership and model-version history.">
  <div class="auth-form"><header class="auth-form-head"><span>CREATE YOUR WORKSPACE</span><h2>Start with one secure account.</h2><p>Only the essentials now. Your sports and model preferences can follow later.</p></header><p v-if="error" class="auth-error" role="alert">{{error}}</p>
    <form novalidate @submit.prevent="submit">
      <label class="auth-field"><span>Display name</span><input v-model.trim="form.displayName" autocomplete="name" placeholder="How NINTH should address you" :aria-invalid="Boolean(fields.displayName)" required><small v-if="fields.displayName">{{fields.displayName}}</small></label>
      <label class="auth-field"><span>Email</span><input v-model.trim="form.email" type="email" autocomplete="email" placeholder="you@example.com" :aria-invalid="Boolean(fields.email)" required><small v-if="fields.email">{{fields.email}}</small></label>
      <label class="auth-field"><span>Password</span><div class="password-wrap"><input v-model="form.password" :type="showPassword?'text':'password'" autocomplete="new-password" placeholder="At least 10 characters" :aria-invalid="Boolean(fields.password)" required><button type="button" :aria-label="showPassword?'Hide password':'Show password'" @click="showPassword=!showPassword"><EyeOff v-if="showPassword"/><Eye v-else/></button></div><small v-if="fields.password">{{fields.password}}</small><div class="strength"><div class="strength-bars"><i v-for="index in 4" :key="index" :class="{active:index<=strength}"></i></div><ul class="requirements"><li :class="{met:checks[0]}">10+ characters</li><li :class="{met:checks[1]&&checks[2]}">Mixed case</li><li :class="{met:checks[3]}">Symbol</li></ul></div></label>
      <label class="auth-field"><span>Confirm password</span><input v-model="form.passwordConfirmation" :type="showPassword?'text':'password'" autocomplete="new-password" placeholder="Repeat your password" :aria-invalid="Boolean(fields.passwordConfirmation)" required><small v-if="fields.passwordConfirmation">{{fields.passwordConfirmation}}</small></label>
      <label class="auth-check legal-check"><input v-model="form.termsAccepted" type="checkbox" required><span>I agree to the <RouterLink to="/legal/terms">Terms of Service</RouterLink> and <RouterLink to="/legal/privacy">Privacy Policy</RouterLink>.</span></label>
      <button class="auth-submit" type="submit" :disabled="auth.loading||!form.termsAccepted">{{auth.loading?'Creating account…':'Create account'}}</button>
    </form><div class="auth-divider">or continue with</div><GoogleSignInButton label="Sign up with Google" :loading="auth.loading" :disabled="!auth.config.googleConfigured" @click="google"/><small v-if="!auth.config.googleConfigured" class="google-unavailable">Google Sign-In becomes available after the OAuth client is connected.</small>
    <p class="auth-switch">Already have an account?<RouterLink :to="{path:'/auth/sign-in',query:{returnTo:returnTo()}}">Sign in</RouterLink></p>
  </div>
</AuthShell></template>
