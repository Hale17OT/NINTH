<script setup>
defineProps({ label: { type: String, default: 'Loading official MLB data' }, detail: { type: String, default: 'Synchronizing the latest available feed.' }, compact: Boolean })
</script>

<template>
  <div class="data-loader panel" :class="{compact}" role="status" aria-live="polite">
    <div class="loader-mark"><i></i><i></i><b>N</b></div>
    <div class="loader-copy"><strong>{{ label }}</strong><span>{{ detail }}</span></div>
    <div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>
  </div>
</template>

<style scoped>
.data-loader{position:relative;isolation:isolate;min-height:170px;padding:28px;display:grid;grid-template-columns:auto 1fr;align-items:center;gap:18px;overflow:hidden}.data-loader::after{content:"";position:absolute;z-index:-1;inset:0;background:linear-gradient(105deg,transparent 25%,color-mix(in srgb,var(--acid) 8%,transparent) 45%,transparent 65%);transform:translateX(-100%);animation:sweep 1.6s ease-in-out infinite}.loader-mark{position:relative;width:52px;height:52px;display:grid;place-items:center}.loader-mark i{position:absolute;inset:0;border:1px solid color-mix(in srgb,var(--acid) 55%,var(--line));border-radius:50%;border-top-color:transparent;animation:orbit 1.15s linear infinite}.loader-mark i:nth-child(2){inset:7px;border-color:color-mix(in srgb,var(--blue) 50%,var(--line));border-bottom-color:transparent;animation-direction:reverse;animation-duration:.85s}.loader-mark b{font:800 13px 'DM Mono';color:var(--acid)}.loader-copy{display:grid;gap:6px}.loader-copy strong{font-size:13px}.loader-copy span{font-size:9px;color:var(--muted)}.skeleton{grid-column:1/-1;display:grid;gap:7px}.skeleton i{height:7px;background:var(--wash);overflow:hidden}.skeleton i:nth-child(1){width:88%}.skeleton i:nth-child(2){width:64%}.skeleton i:nth-child(3){width:76%}.compact{min-height:92px;padding:17px;grid-template-columns:38px 1fr}.compact .loader-mark{width:38px;height:38px}.compact .skeleton{display:none}@keyframes orbit{to{transform:rotate(360deg)}}@keyframes sweep{to{transform:translateX(100%)}}@media(prefers-reduced-motion:reduce){.loader-mark i,.data-loader::after{animation:none}}
</style>
