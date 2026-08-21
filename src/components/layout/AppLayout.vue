<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu, Moon, Search, Sun, X } from 'lucide-vue-next'
import { AnimatePresence, motion, useScroll, useSpring } from 'motion-v'
import { useAppStore } from '../../stores/app'
import { api } from '../../services/api'
import { sportById, sportNavigation, sports } from '../../config/sports'
import TeamLogo from '../team/TeamLogo.vue'
import PlayerHeadshot from '../player/PlayerHeadshot.vue'
import SharedIndicator from '../motion/SharedIndicator.vue'
import ProgressiveBlur from '../motion/ProgressiveBlur.vue'
import AccountMenu from '../../features/auth/components/AccountMenu.vue'

const store = useAppStore()
const router = useRouter()
const route = useRoute()
const query = ref('')
const navOpen = ref(false)
const sportOpen = ref(false)
const focused = ref(false)
const searching = ref(false)
const searchResults = ref({ Teams: [], Players: [], Games: [] })
const searchRoot = ref()
const { scrollYProgress } = useScroll()
const progress = useSpring(scrollYProgress, { stiffness: 260, damping: 38, restDelta: .001 })

const sportId = computed(() => route.meta?.sport || 'baseball')
const activeSport = computed(() => sportId.value === 'platform' ? null : sportById(sportId.value))
const nav = computed(() => activeSport.value?.id === 'baseball'
  ? sportNavigation.baseball
  : activeSport.value ? (sportNavigation[activeSport.value.id] || sportNavigation.default)(activeSport.value) : [['Platform', '/'], ['All-sports builder', '/build']])
const isBaseball = computed(() => activeSport.value?.id === 'baseball')
const isNavActive = path => route.path === path || (path !== '/' && path !== activeSport.value?.route && route.path.startsWith(`${path}/`))
const tickerGames = computed(() => (store.dashboard?.live?.length ? store.dashboard.live : store.dashboard?.today?.length ? store.dashboard.today : store.dashboard?.completed || []).slice(0, 4))
const quickResults = computed(() => Object.entries(searchResults.value).flatMap(([group, items]) => (items || []).slice(0, 4).map(item => ({ ...item, group }))).slice(0, 9))
const gamePath = game => /live|progress|delay/i.test(game.status || '') ? `/live/${game.id}` : `/games/${game.id}`
const tickerState = game => /live|progress|delay/i.test(game.status || '') ? (game.inning || game.status) : game.status
const go = () => { if (query.value.trim()) { router.push({ path: '/search', query: { q: query.value.trim() } }); focused.value = false } }
const pickResult = item => { router.push(item.path); query.value = ''; focused.value = false }
const closeOutside = event => { if (!searchRoot.value?.contains(event.target)) focused.value = false }

let searchTimer
watch(query, value => {
  clearTimeout(searchTimer)
  const term = value.trim()
  if (!isBaseball.value || term.length < 2) { searchResults.value = { Teams: [], Players: [], Games: [] }; searching.value = false; return }
  searching.value = true
  searchTimer = setTimeout(async () => {
    try { searchResults.value = await api.search(term) }
    catch { searchResults.value = { Teams: [], Players: [], Games: [] } }
    finally { searching.value = false }
  }, 240)
})
watch(() => route.fullPath, () => { navOpen.value = false; sportOpen.value = false; focused.value = false })
onMounted(() => document.addEventListener('pointerdown', closeOutside))
onBeforeUnmount(() => { clearTimeout(searchTimer); document.removeEventListener('pointerdown', closeOutside) })
</script>

<template>
  <div class="app-shell" :class="[`workspace-${sportId}`]" :style="activeSport ? {'--workspace-accent':activeSport.accent} : {}">
    <motion.div class="scroll-progress" :style="{ scaleX: progress }" aria-hidden="true"/>
    <header class="workspace-header">
      <div class="header-row">
        <RouterLink to="/" class="brand" aria-label="NINTH home"><img src="/brand/ninth-icon-192.png" alt=""><span>NINTH</span></RouterLink>
        <nav class="sport-nav" aria-label="Sport workspaces">
          <RouterLink to="/" :class="{active:sportId==='platform'}"><span>00</span><b>Platform</b><SharedIndicator v-if="sportId==='platform'" layout-id="sport-nav"/></RouterLink>
          <RouterLink v-for="sport in sports" :key="sport.id" :to="sport.route" :class="{active:sport.id===sportId}" :style="{'--sport':sport.accent}"><span>{{sport.numeral}}</span><b>{{sport.short}}</b><SharedIndicator v-if="sport.id===sportId" layout-id="sport-nav"/></RouterLink>
        </nav>
        <div class="header-actions">
          <form v-if="isBaseball" ref="searchRoot" class="search" @submit.prevent="go">
            <Search :size="17"/><input v-model="query" placeholder="Search MLB" autocomplete="off" aria-label="Search MLB" @focus="focused=true">
            <AnimatePresence>
              <motion.div v-if="focused && query.trim().length >= 2" class="search-menu" :initial="{opacity:0,y:-8,scale:.98}" :animate="{opacity:1,y:0,scale:1}" :exit="{opacity:0,y:-5,scale:.99}">
                <span v-if="searching" class="search-state">SEARCHING OFFICIAL MLB DATA…</span>
                <template v-else-if="quickResults.length"><button v-for="item in quickResults" :key="item.group+item.path" type="button" @pointerdown.prevent="pickResult(item)"><TeamLogo v-if="item.group==='Teams'" :team="item" :size="38"/><PlayerHeadshot v-else-if="item.group==='Players'" :id="item.id" :name="item.name" :size="38"/><i v-else>{{ item.abbr }}</i><span><b>{{ item.name }}</b><small>{{ item.detail }}</small></span></button></template>
                <span v-else class="search-state">NO MATCHES IN OFFICIAL MLB DATA</span>
              </motion.div>
            </AnimatePresence>
          </form>
          <AccountMenu/>
          <button class="theme-toggle icon-only" type="button" :aria-label="store.theme === 'dark' ? 'Use light theme' : 'Use dark theme'" @click="store.toggleTheme()"><Sun v-if="store.theme==='dark'"/><Moon v-else/></button>
          <button class="sport-menu icon-only" type="button" :aria-expanded="sportOpen" aria-label="Choose sport" @click="sportOpen=!sportOpen"><X v-if="sportOpen"/><Menu v-else/></button>
        </div>
      </div>

      <div class="context-row">
        <div class="workspace-title"><small>{{ activeSport ? activeSport.eyebrow : 'DECISION SYSTEM' }}</small><b>{{ activeSport ? activeSport.name : 'All sports' }}</b><em v-if="activeSport">{{ activeSport.status === 'live' ? 'LIVE ANALYTICS' : 'MODEL LAB' }}</em></div>
        <nav class="context-nav" :class="{open:navOpen}" aria-label="Workspace navigation"><RouterLink v-for="item in nav" :key="item[1]" :to="item[1]" :class="{active:isNavActive(item[1])}">{{ item[0] }}<SharedIndicator v-if="isNavActive(item[1])" layout-id="context-nav"/></RouterLink></nav>
        <button v-if="nav.length" class="nav-menu icon-only" type="button" :aria-expanded="navOpen" aria-label="Open workspace navigation" @click="navOpen=!navOpen"><X v-if="navOpen"/><Menu v-else/></button>
      </div>

      <div v-if="isBaseball" class="score-strip"><span class="strip-label"><i :class="{'live-dot':store.dashboard?.live?.length}"></i>{{ store.dashboard?.live?.length ? 'LIVE MLB' : 'TODAY' }}</span><RouterLink v-for="game in tickerGames" :key="game.id" :to="gamePath(game)"><b>{{ game.away.abbr }}</b><em>{{ game.away.score }}</em><span>—</span><em>{{ game.home.score }}</em><b>{{ game.home.abbr }}</b><small>{{ tickerState(game) }}</small></RouterLink><span v-if="!tickerGames.length" class="empty-strip">Official scoreboard syncing</span><span class="feed-state"><i></i> FEEDS CONNECTED</span></div>
    </header>

    <AnimatePresence>
      <motion.aside v-if="sportOpen" class="sport-drawer" :initial="{x:'100%'}" :animate="{x:0}" :exit="{x:'100%'}" :transition="{type:'spring',stiffness:260,damping:31}" aria-label="Sport workspace menu">
        <div class="drawer-head"><span>CHOOSE A WORKSPACE</span><button class="icon-only" type="button" aria-label="Close sport menu" @click="sportOpen=false"><X/></button></div>
        <nav><RouterLink to="/"><small>00</small><b>All sports</b><span>Combined decision system</span></RouterLink><RouterLink v-for="sport in sports" :key="sport.id" :to="sport.route" :style="{'--sport':sport.accent}"><small>{{sport.numeral}}</small><b>{{sport.name}}</b><span>{{sport.eyebrow}}</span></RouterLink></nav>
        <ProgressiveBlur height="70px"/>
      </motion.aside>
      <motion.button v-if="sportOpen" class="drawer-scrim" type="button" aria-label="Close sport menu" :initial="{opacity:0}" :animate="{opacity:1}" :exit="{opacity:0}" @click="sportOpen=false"></motion.button>
    </AnimatePresence>

    <main><div class="content"><slot/></div></main>
  </div>
</template>

<style scoped>
.app-shell{min-height:100vh;--workspace-accent:var(--accent)}
.scroll-progress{position:fixed;z-index:100;inset:0 0 auto;height:3px;transform-origin:left;background:var(--workspace-accent);box-shadow:0 0 18px color-mix(in srgb,var(--workspace-accent) 65%,transparent)}
.workspace-header{position:sticky;top:0;z-index:50;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--paper) 86%,transparent);backdrop-filter:blur(24px) saturate(130%)}
.header-row,.context-row{max-width:var(--content-max);margin:auto;padding:0 var(--content-pad);display:flex;align-items:center}
.header-row{height:var(--header-height);gap:34px}.brand{display:flex;align-items:center;gap:11px;text-decoration:none;flex:none}.brand img{width:34px;height:34px}.brand span{font-size:22px;font-weight:880;letter-spacing:-.06em}
.sport-nav{height:100%;display:flex;align-items:stretch;margin:auto}.sport-nav a{min-width:76px;padding:0 15px;display:flex;align-items:center;justify-content:center;gap:7px;position:relative;text-decoration:none;color:var(--muted);transition:color var(--motion-fast)}.sport-nav a span{font:500 12px 'DM Mono';color:var(--sport,var(--accent))}.sport-nav a b{font-size:12px;letter-spacing:.02em;text-transform:uppercase}.sport-nav a:hover,.sport-nav a.active{color:var(--text)}
.header-actions{display:flex;align-items:center;gap:9px}.theme-toggle,.sport-menu,.nav-menu{width:46px;height:46px;padding:0;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface);color:var(--text);cursor:pointer}.theme-toggle svg,.sport-menu svg,.nav-menu svg{width:18px}.sport-menu{display:none}
.search{position:relative;width:230px;height:46px;display:flex;align-items:center;gap:10px;padding:0 13px;border:1px solid var(--line);background:var(--surface)}.search input{width:100%;min-width:0;min-height:0;border:0;outline:0;background:transparent;color:var(--text);font-size:13px}.search-menu{position:absolute;right:0;top:53px;width:410px;padding:8px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:var(--shadow)}.search-menu button{width:100%;min-height:58px;padding:10px;display:flex;align-items:center;gap:11px;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--text);text-align:left;cursor:pointer}.search-menu button:hover{background:var(--wash)}.search-menu button>span{display:grid;gap:3px}.search-menu b{font-size:14px}.search-menu small{font-size:12px;color:var(--muted)}.search-menu button>i{width:38px;font:700 11px 'DM Mono';font-style:normal}.search-state{display:block;padding:20px 12px;font:600 12px 'DM Mono';color:var(--muted)}
.context-row{min-height:58px;gap:28px;border-top:1px solid var(--line)}.workspace-title{min-width:235px;display:flex;align-items:center;gap:10px}.workspace-title small{font:500 12px 'DM Mono';letter-spacing:.075em;color:var(--muted)}.workspace-title b{font-size:15px;white-space:nowrap}.workspace-title em{padding:6px 8px;background:color-mix(in srgb,var(--workspace-accent) 13%,transparent);color:var(--workspace-accent);font:600 12px 'DM Mono';font-style:normal}.context-nav{height:58px;display:flex;align-items:stretch;gap:2px;overflow:auto;scrollbar-width:none}.context-nav a{padding:0 12px;display:flex;align-items:center;position:relative;text-decoration:none;color:var(--muted);font-size:12px;font-weight:650;white-space:nowrap}.context-nav a:hover,.context-nav a.active{color:var(--text)}.nav-menu{display:none;margin-left:auto}
.score-strip{height:42px;display:flex;align-items:center;gap:28px;padding:0 max(var(--content-pad),calc((100vw - var(--content-max))/2));overflow:hidden;white-space:nowrap;background:var(--contrast);color:var(--on-contrast)}.strip-label{display:flex;align-items:center;gap:8px;font:600 12px 'DM Mono';color:var(--accent)}.strip-label>i:not(.live-dot){width:7px;height:7px;background:var(--accent);border-radius:50%}.score-strip a{display:flex;align-items:center;gap:8px;text-decoration:none;font:500 12px 'DM Mono'}.score-strip a em{font-style:normal;color:var(--accent)}.score-strip a small{color:#909991;margin-left:4px;font-size:12px}.feed-state{margin-left:auto;font:600 11px 'DM Mono';color:#a2aaa1}.feed-state i{display:inline-block;width:6px;height:6px;margin-right:6px;background:var(--green);border-radius:50%}.empty-strip{font:12px 'DM Mono';color:#999}
.content{max-width:var(--content-max);margin:auto;padding:0 var(--content-pad) 96px}
.sport-drawer{position:fixed;z-index:80;inset:0 0 0 auto;width:min(480px,94vw);padding:24px;background:var(--contrast);box-shadow:-40px 0 100px rgba(0,0,0,.44);overflow:auto}.drawer-head{height:66px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2c342d;color:#aab3a9;font:600 12px 'DM Mono'}.drawer-head button{width:46px;height:46px;border:1px solid #323a33;background:transparent;color:#fff}.sport-drawer nav{display:grid}.sport-drawer a{min-height:104px;padding:20px 6px;display:grid;grid-template-columns:46px 1fr;gap:6px 14px;border-bottom:1px solid #293029;text-decoration:none}.sport-drawer small{grid-row:1/3;color:var(--sport,var(--accent));font:500 12px 'DM Mono'}.sport-drawer b{font-size:24px;letter-spacing:-.04em}.sport-drawer a span{color:#9fa79f;font:500 12px 'DM Mono'}.drawer-scrim{position:fixed;z-index:70;inset:0;border:0;background:rgba(0,0,0,.64);backdrop-filter:blur(6px)}
@media(max-width:1180px){.sport-nav{display:none}.sport-menu{display:grid}.header-actions{margin-left:auto}.context-nav{display:none;position:absolute;top:calc(var(--header-height) + 58px);left:0;right:0;height:auto;padding:12px var(--content-pad);flex-wrap:wrap;background:var(--surface);border-bottom:1px solid var(--line);box-shadow:var(--shadow)}.context-nav.open{display:flex}.context-nav a{min-height:46px;border:1px solid var(--line)}.nav-menu{display:grid}.workspace-title{margin-right:auto}}
@media(max-width:700px){.header-row{gap:12px}.brand span{font-size:19px}.brand img{width:31px;height:31px}.workspace-title{min-width:0}.workspace-title small,.workspace-title em{display:none}.workspace-title b{font-size:14px}.search{margin-left:auto;width:150px}.search-menu{position:fixed;left:10px;right:10px;top:72px;width:auto}.context-row{min-height:52px}.score-strip{height:40px;padding:0 var(--content-pad)}.score-strip a:nth-of-type(n+3){display:none}.feed-state{display:none}.content{padding-bottom:88px}}
@media(max-width:500px){.search{display:none}.header-actions{margin-left:auto}.sport-drawer{padding:18px}.sport-drawer a{min-height:92px}.sport-drawer b{font-size:21px}}
</style>
