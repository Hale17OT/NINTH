<script setup>
import { ArrowLeft, BarChart3, ShieldCheck, Sparkles } from 'lucide-vue-next'
import { motion } from 'motion-v'

defineProps({
  eyebrow: { type: String, default: 'NINTH / ACCOUNT' },
  storyTitle: { type: String, default: 'Your intelligence, carried forward.' },
  storyCopy: { type: String, default: 'Keep every model read, builder decision and saved selection connected to one secure workspace.' },
  step: { type: String, default: '01' },
})
</script>

<template>
  <main class="auth-canvas">
    <div class="auth-grid" aria-hidden="true"></div>
    <motion.section class="auth-frame" :initial="{opacity:0,y:22,scale:.985}" :animate="{opacity:1,y:0,scale:1}" :transition="{duration:.64,ease:[.16,1,.3,1]}">
      <aside class="auth-story">
        <div class="story-top">
          <RouterLink to="/" class="auth-brand" aria-label="Return to NINTH"><img src="/brand/ninth-icon-192.png" alt=""><span>NINTH</span></RouterLink>
          <RouterLink to="/" class="back-link"><ArrowLeft :size="16"/> Explore as guest</RouterLink>
        </div>
        <div class="story-copy">
          <span class="story-eyebrow">{{ eyebrow }}</span>
          <h1>{{ storyTitle }}</h1>
          <p>{{ storyCopy }}</p>
          <div class="trust-row"><span><ShieldCheck/> Server-held sessions</span><span><BarChart3/> Auditable builds</span></div>
        </div>
        <div class="signal-field" aria-hidden="true">
          <i class="signal-orbit orbit-one"></i><i class="signal-orbit orbit-two"></i><i class="signal-orbit orbit-three"></i>
          <span class="signal-core"><Sparkles/></span>
          <span class="signal-node node-one"><b>64.8%</b><small>CALIBRATED</small></span>
          <span class="signal-node node-two"><b>+8.4</b><small>EDGE INDEX</small></span>
          <span class="signal-node node-three"><b>9/9</b><small>AUDIT SAMPLE</small></span>
        </div>
        <div class="landscape" aria-hidden="true"><i></i><i></i><i></i></div>
        <footer><span>{{ step }} / SECURE WORKSPACE</span><span>POSTGRESQL · OPAQUE SESSION</span></footer>
      </aside>

      <motion.div class="auth-panel" :initial="{opacity:0,x:24}" :animate="{opacity:1,x:0}" :transition="{delay:.12,duration:.58,ease:[.16,1,.3,1]}">
        <slot />
      </motion.div>
    </motion.section>
  </main>
</template>

<style scoped>
.auth-canvas{position:relative;min-height:100vh;padding:clamp(18px,4vw,62px);display:grid;place-items:center;overflow:hidden;background:radial-gradient(circle at 10% 12%,rgba(151,112,255,.13),transparent 28%),radial-gradient(circle at 88% 78%,rgba(214,255,97,.08),transparent 27%),#070908;color:#f3f6f1}.auth-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:64px 64px;mask-image:linear-gradient(135deg,black,transparent 78%)}
.auth-frame{position:relative;width:min(1240px,100%);min-height:min(790px,calc(100vh - clamp(36px,8vw,124px)));display:grid;grid-template-columns:minmax(0,1.08fr) minmax(440px,.92fr);overflow:hidden;border:1px solid #29302b;border-radius:22px;background:#0e1210;box-shadow:0 38px 120px rgba(0,0,0,.48)}
.auth-story{position:relative;min-height:720px;padding:36px 42px 30px;display:flex;flex-direction:column;overflow:hidden;border-right:1px solid #29302b;background:radial-gradient(circle at 56% 53%,rgba(151,112,255,.22),transparent 29%),linear-gradient(155deg,#171d19 0%,#111612 54%,#0b0e0c 100%)}
.auth-story::before{position:absolute;inset:0;background:linear-gradient(125deg,transparent 20%,rgba(214,255,97,.04) 48%,transparent 72%);content:'';animation:story-scan 8s ease-in-out infinite}.story-top,.story-copy,.signal-field,.auth-story footer{position:relative;z-index:3}.story-top{display:flex;align-items:center;justify-content:space-between;gap:18px}.auth-brand{display:flex;align-items:center;gap:11px;text-decoration:none}.auth-brand img{width:38px;height:38px}.auth-brand span{font-size:22px;font-weight:880;letter-spacing:-.06em}.back-link{min-height:42px;padding:0 12px;display:flex;align-items:center;gap:8px;border:1px solid #313a33;border-radius:7px;color:#aab4aa;font:600 11px 'DM Mono';text-decoration:none}.back-link:hover{border-color:#657066;color:#fff}
.story-copy{width:min(520px,88%);margin-top:78px}.story-eyebrow{color:#d6ff61;font:600 11px 'DM Mono';letter-spacing:.14em}.story-copy h1{max-width:510px;margin:17px 0 16px;font-size:clamp(3rem,5.2vw,5.6rem);font-weight:760;letter-spacing:-.07em;line-height:.92}.story-copy p{max-width:470px;margin:0;color:#aab5aa;font-size:15px;line-height:1.7}.trust-row{margin-top:24px;display:flex;flex-wrap:wrap;gap:10px}.trust-row span{min-height:36px;padding:0 11px;display:flex;align-items:center;gap:8px;border:1px solid #313a33;background:rgba(9,12,10,.54);color:#cad1ca;font:500 10px 'DM Mono';letter-spacing:.04em}.trust-row svg{width:15px;color:#d6ff61}
.signal-field{position:relative;width:360px;height:250px;margin:auto 0 8px auto}.signal-orbit{position:absolute;left:50%;top:50%;border:1px solid rgba(214,255,97,.18);border-radius:50%;transform:translate(-50%,-50%)}.orbit-one{width:92px;height:92px;animation:orbit-pulse 3.2s ease-in-out infinite}.orbit-two{width:174px;height:174px;border-color:rgba(151,112,255,.24)}.orbit-three{width:252px;height:252px;border-style:dashed;animation:spin 28s linear infinite}.signal-core{position:absolute;left:50%;top:50%;width:52px;height:52px;display:grid;place-items:center;border-radius:50%;background:#d6ff61;color:#10130f;transform:translate(-50%,-50%);box-shadow:0 0 50px rgba(214,255,97,.23)}.signal-core svg{width:21px}.signal-node{position:absolute;min-width:102px;padding:11px 12px;display:grid;gap:3px;border:1px solid #354039;background:rgba(9,12,10,.88);backdrop-filter:blur(10px)}.signal-node b{font:600 16px 'DM Mono';color:#fff}.signal-node small{color:#808b81;font:500 9px 'DM Mono';letter-spacing:.09em}.node-one{left:0;top:28px}.node-two{right:0;top:48px}.node-three{right:20px;bottom:4px}
.landscape{position:absolute;z-index:1;left:0;right:0;bottom:0;height:225px;opacity:.72}.landscape i{position:absolute;inset:auto 0 0;height:100%;clip-path:polygon(0 58%,9% 38%,18% 51%,30% 22%,41% 52%,54% 31%,67% 57%,78% 29%,90% 50%,100% 33%,100% 100%,0 100%)}.landscape i:nth-child(1){background:#282233;transform:translateY(-22px);opacity:.8}.landscape i:nth-child(2){background:#171827;transform:translateY(20px) scaleX(1.05)}.landscape i:nth-child(3){height:68%;background:#090b0a;transform:translateY(48px) scaleX(1.14)}.auth-story footer{margin-top:auto;display:flex;justify-content:space-between;gap:18px;color:#737e74;font:500 9px 'DM Mono';letter-spacing:.09em}
.auth-panel{padding:clamp(34px,5vw,72px);display:flex;align-items:center;background:linear-gradient(145deg,rgba(255,255,255,.018),transparent 34%),#101411}.auth-panel :deep(>*){width:100%;max-width:490px;margin:auto}
@keyframes story-scan{0%,100%{transform:translateX(-18%);opacity:.4}50%{transform:translateX(18%);opacity:1}}@keyframes orbit-pulse{0%,100%{transform:translate(-50%,-50%) scale(.94);opacity:.55}50%{transform:translate(-50%,-50%) scale(1.08);opacity:1}}@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}
@media(max-width:930px){.auth-canvas{padding:16px}.auth-frame{grid-template-columns:1fr}.auth-story{min-height:280px;padding:26px 28px;border-right:0;border-bottom:1px solid #29302b}.story-copy{width:75%;margin-top:46px}.story-copy h1{font-size:clamp(2.7rem,8vw,4.5rem)}.story-copy p,.trust-row,.signal-node,.auth-story footer{display:none}.signal-field{position:absolute;right:-55px;bottom:-26px;width:280px;height:280px;margin:0}.landscape{height:130px}.auth-panel{padding:48px 30px}}
@media(max-width:560px){.auth-canvas{padding:0;place-items:stretch}.auth-frame{min-height:100vh;border:0;border-radius:0}.auth-story{min-height:210px;padding:22px 20px}.back-link{font-size:0;width:42px;padding:0;justify-content:center}.back-link svg{width:17px}.story-copy{width:80%;margin-top:34px}.story-copy h1{margin-top:11px;font-size:2.45rem}.story-copy p{display:none}.signal-field{right:-102px;bottom:-78px}.auth-panel{padding:38px 20px 54px;align-items:flex-start}}
@media(prefers-reduced-motion:reduce){.auth-story::before,.orbit-one,.orbit-three{animation:none}}
</style>
