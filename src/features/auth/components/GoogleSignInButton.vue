<script setup>
defineProps({ loading: Boolean, disabled: Boolean, label: { type: String, default: 'Continue with Google' } })
defineEmits(['click'])
</script>
<template>
  <button class="google-button" type="button" :disabled="disabled || loading" @click="$emit('click')">
    <svg aria-hidden="true" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.6 12.2c0-.7-.1-1.5-.2-2.2H12v4.3h5.9a5 5 0 0 1-2.2 3.2v2.8h3.6c2.1-1.9 3.3-4.8 3.3-8.1Z"/><path fill="#34A853" d="M12 23c3 0 5.5-1 7.3-2.7l-3.6-2.8c-1 .7-2.3 1-3.7 1-2.8 0-5.2-1.9-6.1-4.5H2.2v2.9A11 11 0 0 0 12 23Z"/><path fill="#FBBC05" d="M5.9 14a6.6 6.6 0 0 1 0-4V7.1H2.2a11 11 0 0 0 0 9.8L5.9 14Z"/><path fill="#EA4335" d="M12 5.5c1.6 0 3 .6 4.2 1.7l3.2-3.1A10.7 10.7 0 0 0 12 1 11 11 0 0 0 2.2 7.1L5.9 10c.9-2.6 3.3-4.5 6.1-4.5Z"/></svg>
    <span>{{ loading ? 'Opening Google…' : label }}</span>
  </button>
</template>
<style scoped>
.google-button{width:100%;min-height:52px;padding:0 16px;display:flex;align-items:center;justify-content:center;gap:12px;border:1px solid #374038;background:#171c18;color:#f3f6f1;font-size:13px;font-weight:700;cursor:pointer;transition:border-color .2s,background .2s,transform .2s}.google-button:hover:not(:disabled){border-color:#667167;background:#1b211c;transform:translateY(-1px)}.google-button:disabled{opacity:.56;cursor:not-allowed}.google-button svg{width:19px;height:19px;flex:none}
</style>
