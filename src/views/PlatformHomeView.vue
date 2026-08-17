<script setup>
import { computed, onMounted, ref } from 'vue'
import { AnimatePresence, motion, useReducedMotion } from 'motion-v'
import { ArrowRight, ArrowUpRight, Binary, Database, Layers3, ShieldCheck, Sparkles } from 'lucide-vue-next'
import { sports } from '../config/sports'
import { useAppStore } from '../stores/app'
import MotionPanel from '../components/motion/MotionPanel.vue'
import AnimatedGroup from '../components/motion/AnimatedGroup.vue'
import TextEffect from '../components/motion/TextEffect.vue'
import TransitionPanel from '../components/motion/TransitionPanel.vue'
import BorderTrail from '../components/motion/BorderTrail.vue'
import EvidenceBadge from '../components/ui/EvidenceBadge.vue'
import AnimatedNumber from '../components/ui/AnimatedNumber.vue'
import SportVisual from '../components/ui/SportVisual.vue'
import { sportTransition } from '../motion/system'

const store = useAppStore()
const reduced = useReducedMotion()
const activeId = ref('baseball')
const active = computed(() => sports.find(sport => sport.id === activeId.value) || sports[0])
const featured = computed(() => store.dashboard?.live?.[0] || store.dashboard?.today?.[0] || null)
const strongest = computed(() => featured.value?.brief || null)
const gameCount = computed(() => (store.dashboard?.live?.length || 0) + (store.dashboard?.today?.length || 0))
const percent = value => value ? `${(Number(value) * 100).toFixed(1)}%` : 'Pending'
const setActive = id => { activeId.value = id }

onMounted(() => store.load())
</script>

<template>
  <div class="platform-home">
    <section class="platform-hero" :style="{'--hero-accent': active.accent}">
      <div class="hero-grid" aria-hidden="true"></div>
      <motion.div class="trajectory" :animate="{backgroundColor:active.accent}" :transition="{duration:.45}"><i></i><span></span></motion.div>
      <div class="hero-copy">
        <div class="hero-topline"><EvidenceBadge state="brand">MULTI-SPORT DECISION INTELLIGENCE</EvidenceBadge><span class="mono">SYSTEM / 09</span></div>
        <h1><TextEffect text="NINTH" as="span" by="chars"/></h1>
        <TransitionPanel :panel-key="active.id" class="hero-panel">
          <p class="sport-kicker mono">{{ active.numeral }} / {{ active.name.toUpperCase() }} · {{ active.eyebrow }}</p>
          <h2>Read the game.<br><i>Price the uncertainty.</i></h2>
          <p class="hero-description">{{ active.description }}</p>
          <div class="hero-actions">
            <RouterLink to="/build" class="primary">Build across sports <ArrowRight/></RouterLink>
            <RouterLink :to="active.route" class="secondary">Enter {{active.short}} intelligence <ArrowUpRight/></RouterLink>
          </div>
        </TransitionPanel>
      </div>

      <AnimatePresence mode="popLayout">
        <motion.div
          :key="active.id"
          class="hero-object"
          :initial="reduced ? false : sportTransition.initial"
          :animate="sportTransition.animate"
          :exit="reduced ? undefined : sportTransition.exit"
          :transition="sportTransition.transition"
        ><SportVisual :sport="active.id" :accent="active.accent"/></motion.div>
      </AnimatePresence>

      <motion.aside class="hero-signal" layout :style="{'--signal':active.accent}">
        <BorderTrail/>
        <span class="mono">LIVE DECISION WINDOW</span>
        <template v-if="featured">
          <h3>{{ featured.away?.abbr }} <i>at</i> {{ featured.home?.abbr }}</h3>
          <p>{{ strongest?.modelTeam?.abbr || 'Model slate' }} · {{ percent(strongest?.modelProbability) }}</p>
        </template>
        <template v-else><h3>FEED SYNC</h3><p>Official events are being verified.</p></template>
      </motion.aside>

      <div class="sport-switcher" role="tablist" aria-label="Choose sport workspace">
        <button v-for="sport in sports" :key="sport.id" type="button" role="tab" :aria-selected="activeId===sport.id" :class="{active:activeId===sport.id}" :style="{'--sport':sport.accent}" @click="setActive(sport.id)">
          <motion.span v-if="activeId===sport.id" layout-id="home-sport-active" class="switch-active" :transition="{type:'spring',stiffness:360,damping:34}"/>
          <small>{{sport.numeral}}</small><b>{{sport.short}}</b><em>{{sport.name}}</em>
        </button>
      </div>
    </section>

    <MotionPanel class="hero-bento" :delay=".04">
      <article class="feature-card card-shell">
        <BorderTrail :active="Boolean(featured)"/>
        <EvidenceBadge :state="featured ? 'live' : 'neutral'">{{featured ? 'FEATURED MATCHUP' : 'OFFICIAL SLATE'}}</EvidenceBadge>
        <template v-if="featured"><h3>{{featured.away?.name}} <span>at</span> {{featured.home?.name}}</h3><p>{{featured.status}} · {{featured.time}} · {{featured.stadium}}</p><RouterLink :to="`/games/${featured.id}`">Read the matchup <ArrowRight/></RouterLink></template>
        <template v-else><h3>MLB feed synchronizing</h3><p>The platform waits for official data instead of inventing a featured event.</p></template>
      </article>
      <article class="edge-card card-shell">
        <EvidenceBadge :state="strongest?.modelTeam ? 'positive' : 'warning'">STRONGEST AUDITED EDGE</EvidenceBadge>
        <div class="edge-value"><strong>{{strongest?.modelTeam?.abbr || '—'}}</strong><h3>{{percent(strongest?.modelProbability)}}</h3></div>
        <p>{{strongest?.combinedStandingLabel || 'Waiting for a complete production-grade matchup snapshot.'}}</p>
      </article>
      <RouterLink to="/build" class="build-card">
        <BorderTrail/><Layers3/><span class="mono">COMBINED BUILDER</span><h3>One card.<br>Every arena.</h3><p>Join only evidence-eligible outputs while controlling shared exposure.</p><i><ArrowUpRight/></i>
      </RouterLink>
    </MotionPanel>

    <MotionPanel class="analytics-feature" :delay=".06">
      <header><div><EvidenceBadge state="brand">ANALYTICS & INSIGHTS</EvidenceBadge><h2>Sharp evidence.<br><i>Fewer assumptions.</i></h2></div><RouterLink to="/model">Open model lab <ArrowRight/></RouterLink></header>
      <div class="analytics-grid">
        <article class="metric-story coverage"><span class="mono">01 / CURRENT COVERAGE</span><strong class="mono"><AnimatedNumber :value="gameCount"/></strong><p>MLB events on the current live and upcoming production board.</p><div class="sparkline"><i v-for="height in [28,42,35,58,50,73,64,88]" :key="height" :style="{height:`${height}%`}"></i></div></article>
        <article class="metric-story calibration"><span class="mono">02 / EVIDENCE STANDARD</span><strong>CALIBRATED</strong><p>Brier quality, Wilson bounds and chronological audits precede builder promotion.</p><div class="rings"><i></i><i></i><i></i><b>9</b></div></article>
        <article class="heatmap"><span class="mono">03 / DECISION TERRAIN</span><div class="heat-grid"><i v-for="n in 48" :key="n" :class="{hot:[8,13,17,18,24,29,37,44].includes(n),warm:[4,9,12,23,30,32,41,46].includes(n)}"></i></div><p>Signal density is visualized only when supported by a real prediction board.</p></article>
      </div>
    </MotionPanel>

    <section class="workspace-section">
      <header><div><EvidenceBadge state="brand">SPORT WORKSPACES</EvidenceBadge><p class="mono">05 ARENAS / ONE STANDARD</p></div><h2>Separate intelligence.<br><i>One exacting system.</i></h2></header>
      <div class="sport-stack">
        <MotionPanel v-for="(sport,index) in sports" :key="sport.id" :delay="index*.04">
          <RouterLink :to="sport.route" :style="{'--sport':sport.accent}">
            <span class="number mono">{{ sport.numeral }}</span>
            <div class="workspace-copy"><small class="mono">{{ sport.eyebrow }}</small><h3>{{ sport.name }}</h3><p>{{sport.description}}</p></div>
            <em class="mono">{{ sport.status === 'live' ? 'PRODUCTION' : 'RESEARCH LAB' }}</em>
            <img :src="`/media/sports/${sport.id}-hero.png`" alt="" loading="lazy">
            <span class="workspace-arrow"><ArrowUpRight/></span>
          </RouterLink>
        </MotionPanel>
      </div>
    </section>

    <AnimatedGroup as="section" class="platform-contract" v-slot="{ item }">
      <motion.article v-bind="item"><Database/><span class="mono">01</span><div><b>Point-in-time data</b><p>Only information available before the event enters a training row.</p></div></motion.article>
      <motion.article v-bind="item"><Binary/><span class="mono">02</span><div><b>Sport-native models</b><p>Possessions, drives, scorelines, maps and innings retain separate engines.</p></div></motion.article>
      <motion.article v-bind="item"><ShieldCheck/><span class="mono">03</span><div><b>Evidence-gated release</b><p>Research becomes production only after locked chronological and live audits.</p></div></motion.article>
      <motion.article v-bind="item" class="contract-signal"><Sparkles/><span class="mono">09</span><div><b>One decision system</b><p>Every surface shows provenance, confidence and uncertainty without decoration masquerading as evidence.</p></div></motion.article>
    </AnimatedGroup>
  </div>
</template>

<style scoped>
.platform-home{padding:24px 0 96px}.platform-hero{position:relative;min-height:clamp(720px,78vh,900px);display:grid;grid-template-columns:minmax(0,1.08fr) minmax(480px,.92fr);align-items:center;overflow:hidden;border:1px solid var(--line);border-radius:24px;background:#030504;color:#f3f5ee;isolation:isolate}.platform-hero::before{position:absolute;inset:0;background:radial-gradient(circle at 75% 42%,color-mix(in srgb,var(--hero-accent) 14%,transparent),transparent 35%),linear-gradient(115deg,rgba(255,255,255,.026),transparent 36%);content:''}.hero-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.028) 1px,transparent 1px);background-size:88px 88px;mask-image:linear-gradient(90deg,rgba(0,0,0,.7),transparent 76%)}.trajectory{position:absolute;z-index:0;left:30%;right:-15%;top:57%;height:82px;transform:rotate(-24deg);box-shadow:0 0 64px color-mix(in srgb,var(--hero-accent) 24%,transparent)}.trajectory i{position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.42),transparent)}.trajectory span{position:absolute;inset:-26px 0;border-top:1px solid color-mix(in srgb,var(--hero-accent) 30%,transparent);border-bottom:1px solid color-mix(in srgb,var(--hero-accent) 18%,transparent)}
.hero-copy{position:relative;z-index:4;padding:clamp(42px,5.2vw,88px);align-self:stretch;display:flex;flex-direction:column;justify-content:center}.hero-topline{display:flex;align-items:center;justify-content:space-between;gap:18px;max-width:750px}.hero-topline>span{color:#768077;font-size:12px;letter-spacing:.1em}.hero-copy h1{margin:24px 0 0;font-size:var(--text-display);font-weight:530;line-height:.72;letter-spacing:-.095em}.hero-panel{margin-top:clamp(50px,7vh,82px);min-height:245px}.sport-kicker{margin:0 0 15px;color:var(--hero-accent);font-size:12px;letter-spacing:.08em}.hero-panel h2{margin:0;font-size:clamp(2.75rem,4.4vw,4.9rem);line-height:.91;letter-spacing:-.065em}.hero-panel h2 i{color:#8e9790;font-style:normal}.hero-description{max-width:620px;margin:19px 0 0;color:#a8b0aa;font-size:15px;line-height:1.65}.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:30px}.hero-actions a{min-height:50px;padding:0 18px;display:flex;align-items:center;gap:18px;border:1px solid color-mix(in srgb,var(--hero-accent) 35%,#313833);background:var(--hero-accent);color:#071005;text-decoration:none;font-size:12px;font-weight:760;text-transform:uppercase;letter-spacing:.035em}.hero-actions a.secondary{background:rgba(3,5,4,.72);color:#f3f5ee}.hero-actions svg{width:16px}
.hero-object{position:absolute;z-index:2;right:-1%;top:7%;display:grid;place-items:center}.hero-signal{position:absolute;z-index:6;right:clamp(28px,4vw,68px);top:9%;width:230px;padding:18px 19px;border:1px solid color-mix(in srgb,var(--signal) 30%,#2e3530);background:rgba(4,7,5,.76);backdrop-filter:blur(16px)}.hero-signal>span{color:var(--signal);font-size:12px;letter-spacing:.08em}.hero-signal h3{margin:23px 0 6px;font-size:28px;letter-spacing:-.05em}.hero-signal h3 i{color:#7e8780;font-size:14px;font-style:normal}.hero-signal p{margin:0;color:#adb5ae;font-size:12px}
.sport-switcher{position:absolute;z-index:8;left:clamp(30px,5.2vw,88px);right:clamp(30px,5.2vw,88px);bottom:24px;display:grid;grid-template-columns:repeat(5,1fr);border:1px solid #293029;background:rgba(3,5,4,.78);backdrop-filter:blur(18px)}.sport-switcher button{position:relative;min-height:68px;padding:10px 16px;display:grid;grid-template-columns:24px 44px 1fr;align-items:center;text-align:left;border:0;border-right:1px solid #293029;background:transparent;color:#818a83;cursor:pointer;overflow:hidden}.sport-switcher button:last-child{border-right:0}.switch-active{position:absolute;inset:0;background:color-mix(in srgb,var(--sport) 13%,#080b09);border-top:2px solid var(--sport)}.sport-switcher small,.sport-switcher b,.sport-switcher em{position:relative}.sport-switcher small{color:var(--sport);font:500 12px 'DM Mono'}.sport-switcher b{font:740 13px 'DM Mono'}.sport-switcher em{font-size:12px;font-style:normal}.sport-switcher button.active{color:#f3f5ee}
.hero-bento{position:relative;z-index:3;display:grid;grid-template-columns:1.25fr 1fr .9fr;gap:12px;margin:-1px 0 96px;padding:12px 0 0}.card-shell,.build-card{position:relative;min-height:260px;padding:30px;border:1px solid var(--line);border-radius:16px;background:var(--surface);overflow:hidden}.card-shell{display:flex;flex-direction:column}.hero-bento h3{margin:auto 0 12px;font-size:clamp(1.7rem,2.8vw,2.75rem);line-height:1;letter-spacing:-.055em}.hero-bento p{margin:0;color:var(--muted);font-size:14px;line-height:1.6}.feature-card h3 span{color:var(--muted);font-weight:430}.feature-card a{width:max-content;margin-top:22px;display:flex;align-items:center;gap:10px;color:var(--accent);text-decoration:none;font-size:12px;font-weight:760;text-transform:uppercase}.feature-card svg{width:15px}.edge-value{margin-top:auto;display:flex;align-items:end;justify-content:space-between;gap:16px}.edge-card strong{color:var(--green);font:700 4.5rem/.8 'DM Mono';letter-spacing:-.09em}.edge-card h3{margin:0}.build-card{display:flex;flex-direction:column;background:var(--accent);color:#071005;text-decoration:none}.build-card>svg{width:32px}.build-card>span{margin-top:auto;font-size:11px}.build-card h3{margin:12px 0}.build-card p{color:rgba(7,16,5,.7)}.build-card>i{position:absolute;right:22px;top:22px;width:42px;height:42px;display:grid;place-items:center;border:1px solid rgba(7,16,5,.32);font-style:normal}
.analytics-feature{padding:clamp(30px,4vw,64px);border:1px solid var(--line);border-radius:24px;background:var(--surface)}.analytics-feature>header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:48px}.analytics-feature h2,.workspace-section h2{margin:18px 0 0;font-size:clamp(3rem,5.6vw,6rem);line-height:.9;letter-spacing:-.075em}.analytics-feature h2 i,.workspace-section h2 i{color:var(--muted);font-style:normal}.analytics-feature>header a{min-height:48px;padding:0 16px;display:flex;align-items:center;gap:12px;border:1px solid var(--line);text-decoration:none;font-size:12px;font-weight:750;text-transform:uppercase}.analytics-feature>header svg{width:15px}.analytics-grid{display:grid;grid-template-columns:1fr 1fr 1.25fr;gap:10px}.analytics-grid>article{position:relative;min-height:330px;padding:26px;overflow:hidden;border:1px solid var(--line);border-radius:14px;background:var(--paper)}.analytics-grid article>span{color:var(--muted);font-size:11px;letter-spacing:.07em}.metric-story{display:flex;flex-direction:column}.metric-story>strong{margin-top:auto;font-size:5.7rem;line-height:.78;letter-spacing:-.1em}.metric-story p,.heatmap p{max-width:330px;color:var(--muted);font-size:14px;line-height:1.6}.sparkline{height:92px;display:flex;align-items:end;gap:7px;margin-top:22px}.sparkline i{flex:1;background:linear-gradient(var(--accent),color-mix(in srgb,var(--accent) 12%,transparent))}.calibration>strong{font-size:2.25rem;color:var(--green);letter-spacing:-.06em}.rings{position:absolute;right:-34px;bottom:-34px;width:220px;height:220px;display:grid;place-items:center}.rings i{position:absolute;border:1px solid color-mix(in srgb,var(--accent) 34%,transparent);border-radius:50%}.rings i:nth-child(1){inset:0}.rings i:nth-child(2){inset:31px}.rings i:nth-child(3){inset:62px}.rings b{color:var(--accent);font:800 3.2rem 'DM Mono'}.heat-grid{display:grid;grid-template-columns:repeat(8,1fr);gap:5px;margin:38px 0 28px}.heat-grid i{aspect-ratio:1;background:#171c18;border:1px solid #242b25}.heat-grid i.warm{background:color-mix(in srgb,var(--accent) 28%,#151a16)}.heat-grid i.hot{background:var(--accent);box-shadow:0 0 20px color-mix(in srgb,var(--accent) 42%,transparent)}
.workspace-section{padding:120px 0 82px}.workspace-section>header{display:grid;grid-template-columns:260px 1fr;align-items:start}.workspace-section>header p{margin:22px 0 0;color:var(--muted);font-size:12px;letter-spacing:.07em}.workspace-section h2{margin:0}.sport-stack{margin-top:60px;border-top:1px solid var(--line)}.sport-stack a{position:relative;min-height:190px;padding:28px 24px;display:grid;grid-template-columns:70px minmax(0,1fr) 150px 220px 50px;align-items:center;gap:24px;overflow:hidden;border-bottom:1px solid var(--line);text-decoration:none}.sport-stack a::before{position:absolute;inset:0;background:linear-gradient(90deg,color-mix(in srgb,var(--sport) 13%,transparent),transparent 74%);content:'';transform:translateX(-100%);transition:transform .48s var(--ease-emphasized)}.sport-stack a:hover::before{transform:none}.sport-stack a>*{position:relative}.sport-stack .number{color:var(--sport);font-size:12px}.sport-stack small{color:var(--sport);font-size:12px;letter-spacing:.07em}.sport-stack h3{margin:7px 0 8px;font-size:2.35rem;letter-spacing:-.055em}.sport-stack p{max-width:720px;margin:0;color:var(--muted);font-size:14px;line-height:1.55}.sport-stack em{color:var(--sport);font-size:12px;font-style:normal}.sport-stack img{align-self:end;width:200px;height:150px;object-fit:contain;filter:drop-shadow(0 24px 20px rgba(0,0,0,.35));transform:translateY(32px) rotate(-7deg);transition:transform .5s var(--ease-emphasized)}.sport-stack a:hover img{transform:translateY(16px) rotate(-3deg) scale(1.05)}.workspace-arrow{width:46px;height:46px;display:grid;place-items:center;border:1px solid var(--line);color:var(--sport)}
.platform-contract{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:16px;overflow:hidden}.platform-contract article{min-height:230px;padding:30px;display:grid;grid-template-columns:34px 1fr;gap:16px;background:var(--surface)}.platform-contract svg{color:var(--accent)}.platform-contract article>span{justify-self:end;color:var(--muted);font-size:12px}.platform-contract div{grid-column:1/-1;margin-top:auto}.platform-contract b{font-size:19px}.platform-contract p{margin:9px 0 0;color:var(--muted);font-size:13px;line-height:1.6}.contract-signal{background:var(--accent)!important;color:#071005}.contract-signal svg,.contract-signal p,.contract-signal>span{color:#25320d!important}
@media(max-width:1180px){.platform-hero{grid-template-columns:1fr}.hero-object{right:-15%;opacity:.7}.hero-copy{max-width:790px}.hero-signal{display:none}.sport-switcher{grid-template-columns:repeat(5,minmax(90px,1fr));overflow:auto}.sport-switcher button{grid-template-columns:22px 1fr}.sport-switcher em{display:none}.hero-bento{grid-template-columns:1fr 1fr}.build-card{grid-column:1/-1}.analytics-grid{grid-template-columns:1fr 1fr}.heatmap{grid-column:1/-1}.workspace-section>header{grid-template-columns:1fr;gap:24px}.sport-stack a{grid-template-columns:55px 1fr 120px 150px 46px}.platform-contract{grid-template-columns:1fr 1fr}}
@media(max-width:740px){.platform-home{padding-top:12px}.platform-hero{min-height:780px;border-radius:16px}.hero-copy{align-self:start;padding:42px 22px}.hero-topline>span{display:none}.hero-copy h1{font-size:clamp(5.2rem,26vw,8.2rem)}.hero-panel{margin-top:42px;min-height:280px}.hero-panel h2{font-size:clamp(2.45rem,11vw,3.75rem)}.hero-description{max-width:390px;font-size:14px}.hero-actions a{width:100%;justify-content:space-between}.hero-object{top:38%;right:-28%;opacity:.56}.sport-switcher{left:14px;right:14px;bottom:14px}.sport-switcher button{min-width:88px;min-height:62px;padding:9px}.hero-bento{grid-template-columns:1fr;margin-bottom:64px}.build-card{grid-column:auto}.card-shell,.build-card{min-height:230px;padding:24px}.analytics-feature{padding:28px 16px}.analytics-feature>header{align-items:flex-start;flex-direction:column}.analytics-feature h2,.workspace-section h2{font-size:clamp(2.8rem,14vw,4.6rem)}.analytics-grid{grid-template-columns:1fr}.heatmap{grid-column:auto}.workspace-section{padding:80px 0 56px}.sport-stack a{min-height:160px;padding:22px 8px;grid-template-columns:36px 1fr 42px}.sport-stack em,.sport-stack p,.sport-stack img{display:none}.sport-stack h3{font-size:1.8rem}.workspace-arrow{width:42px;height:42px}.platform-contract{grid-template-columns:1fr}.platform-contract article{min-height:190px}}
</style>
