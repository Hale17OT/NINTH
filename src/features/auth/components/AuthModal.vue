<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import { AnimatePresence, motion } from 'motion-v'
import GoogleSignInButton from './GoogleSignInButton.vue'
import { useAuthStore } from '../stores/auth'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps({ open: Boolean, title: { type: String, default: 'Save your intelligence' }, copy: { type: String, default: 'Create a free account or sign in to keep predictions, builders and personalized analysis.' } })
const emit = defineEmits(['close'])
const auth = useAuthStore(), route = useRoute(), router = useRouter()
const dialog = ref()
const destination = () => route.fullPath.startsWith('/') ? route.fullPath : '/'
const go = path => { emit('close'); router.push({ path, query: { returnTo: destination() } }) }
const google = async () => { try { await auth.loginWithGoogle(destination()) } catch {} }
const escape = event => { if (event.key === 'Escape' && props.open) emit('close') }
watch(() => props.open, async open => { if (open) { await nextTick(); dialog.value?.focus() } })
window.addEventListener('keydown', escape)
onBeforeUnmount(() => window.removeEventListener('keydown', escape))
</script>
<template>
  <Teleport to="body"><AnimatePresence>
    <motion.div v-if="open" class="auth-modal-wrap" :initial="{opacity:0}" :animate="{opacity:1}" :exit="{opacity:0}" @click.self="$emit('close')">
      <motion.section ref="dialog" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title" tabindex="-1" :initial="{opacity:0,y:22,scale:.97}" :animate="{opacity:1,y:0,scale:1}" :exit="{opacity:0,y:12,scale:.98}">
        <button class="modal-close icon-only" type="button" aria-label="Close" @click="$emit('close')"><X/></button>
        <span>NINTH / ACCOUNT REQUIRED</span><h2 id="auth-modal-title">{{ title }}</h2><p>{{ copy }}</p>
        <GoogleSignInButton :loading="auth.loading" :disabled="!auth.config.googleConfigured" @click="google"/>
        <div class="modal-actions"><button type="button" @click="go('/auth/sign-in')">Sign in</button><button type="button" @click="go('/auth/sign-up')">Create account</button></div>
      </motion.section>
    </motion.div>
  </AnimatePresence></Teleport>
</template>
<style scoped>
.auth-modal-wrap{position:fixed;z-index:200;inset:0;padding:18px;display:grid;place-items:center;background:rgba(3,5,4,.78);backdrop-filter:blur(16px)}section{position:relative;width:min(480px,100%);padding:38px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:var(--shadow)}section>span{color:var(--accent);font:600 11px 'DM Mono';letter-spacing:.12em}h2{margin:16px 0 10px;font-size:32px;letter-spacing:-.05em}p{margin:0 0 24px;color:var(--muted);font-size:14px;line-height:1.65}.modal-close{position:absolute;right:16px;top:16px;width:42px;height:42px;border:1px solid var(--line);background:var(--surface-2);color:var(--text)}.modal-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}.modal-actions button{min-height:48px;border:1px solid var(--line);background:var(--surface-2);color:var(--text);font-weight:700}.modal-actions button:last-child{border-color:var(--accent);background:var(--accent);color:#10130f}
</style>
