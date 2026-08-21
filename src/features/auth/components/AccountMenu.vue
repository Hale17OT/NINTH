<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Bookmark, ChevronDown, LogOut, Settings, UserRound } from 'lucide-vue-next'
import { AnimatePresence, motion } from 'motion-v'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore(), router = useRouter(), open = ref(false), root = ref()
const firstName = computed(() => auth.user?.displayName?.split(/\s+/)[0] || 'Account')
const closeOutside = event => { if (!root.value?.contains(event.target)) open.value = false }
const logout = async () => { open.value = false; await auth.logout(); router.push('/') }
onMounted(() => document.addEventListener('pointerdown', closeOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeOutside))
</script>
<template>
  <div v-if="auth.hydrated" ref="root" class="account-slot">
    <template v-if="auth.isAuthenticated">
      <button class="account-trigger" type="button" aria-haspopup="menu" :aria-expanded="open" @click="open=!open" @keydown.esc.stop="open=false">
        <img v-if="auth.user.avatarUrl" :src="auth.user.avatarUrl" alt=""><span v-else>{{ auth.initials }}</span><b>{{ firstName }}</b><ChevronDown/>
      </button>
      <AnimatePresence><motion.div v-if="open" class="account-popover" role="menu" :initial="{opacity:0,y:-8,scale:.98}" :animate="{opacity:1,y:0,scale:1}" :exit="{opacity:0,y:-5,scale:.985}" @keydown.esc.stop="open=false">
        <header><span>{{ auth.initials }}</span><div><b>{{ auth.user.displayName }}</b><small>{{ auth.user.email }}</small></div></header>
        <nav><RouterLink role="menuitem" to="/account" @click="open=false"><UserRound/> Account</RouterLink><RouterLink role="menuitem" to="/saved" @click="open=false"><Bookmark/> Saved</RouterLink><RouterLink role="menuitem" to="/account?panel=preferences" @click="open=false"><Settings/> Settings</RouterLink></nav>
        <button class="sign-out" type="button" @click="logout"><LogOut/> Sign out</button>
      </motion.div></AnimatePresence>
    </template>
    <div v-else class="guest-actions"><RouterLink to="/auth/sign-in">Sign in</RouterLink><RouterLink class="create-account" to="/auth/sign-up">Create account</RouterLink></div>
  </div>
</template>
<style scoped>
.account-slot{position:relative;flex:none}.account-trigger{min-height:46px;padding:4px 9px 4px 5px;display:flex;align-items:center;gap:8px;border:1px solid var(--line);background:var(--surface);cursor:pointer}.account-trigger>span,.account-trigger img,.account-popover header>span{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:50%;background:var(--accent);color:#10130f;font:700 11px 'DM Mono';object-fit:cover}.account-trigger b{max-width:80px;overflow:hidden;text-overflow:ellipsis;font-size:12px}.account-trigger svg{width:14px;color:var(--muted)}.account-popover{position:absolute;z-index:85;right:0;top:53px;width:300px;padding:8px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:var(--shadow)}.account-popover header{padding:12px;display:flex;align-items:center;gap:11px;border-bottom:1px solid var(--line)}.account-popover header>span{width:40px;height:40px}.account-popover header div{min-width:0;display:grid;gap:3px}.account-popover header b{font-size:13px}.account-popover header small{overflow:hidden;color:var(--muted);font:500 10px 'DM Mono';text-overflow:ellipsis}.account-popover nav{display:grid;padding:7px 0}.account-popover nav a,.sign-out{min-height:44px;padding:0 12px;display:flex;align-items:center;gap:10px;border:0;background:transparent;color:var(--text);font-size:12px;font-weight:650;text-decoration:none}.account-popover nav a:hover,.sign-out:hover{background:var(--wash)}.account-popover svg{width:16px;color:var(--muted)}.sign-out{width:100%;border-top:1px solid var(--line);color:var(--red);cursor:pointer}.sign-out svg{color:currentColor}.guest-actions{display:flex;align-items:center;gap:5px}.guest-actions a{min-height:42px;padding:0 11px;display:flex;align-items:center;font-size:11px;font-weight:700;text-decoration:none}.guest-actions .create-account{background:var(--accent);color:#10130f}.guest-actions a:first-child{border:1px solid var(--line);background:var(--surface)}
@media(max-width:700px){.account-trigger b{display:none}.guest-actions a{width:42px;padding:0;justify-content:center;font-size:0}.guest-actions .create-account{width:52px}.guest-actions a:first-child::after{content:'IN';font:700 11px 'DM Mono'}.guest-actions .create-account::after{content:'JOIN';font:700 10px 'DM Mono'}.account-popover{position:fixed;right:10px;top:68px;left:10px;width:auto}}
</style>
