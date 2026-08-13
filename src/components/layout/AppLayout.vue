<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleDot, Diamond, Dribbble, Gamepad2, Menu, Search, Shield, X } from 'lucide-vue-next'
import { useAppStore } from '../../stores/app'
import { api } from '../../services/api'
import { sportById, sportNavigation, sports } from '../../config/sports'
import TeamLogo from '../team/TeamLogo.vue'
import PlayerHeadshot from '../player/PlayerHeadshot.vue'

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

const icons = { baseball: Diamond, football: CircleDot, 'american-football': Shield, basketball: Dribbble, esports: Gamepad2 }
const sportId = computed(() => route.meta?.sport || 'baseball')
const activeSport = computed(() => sportId.value === 'platform' ? null : sportById(sportId.value))
const nav = computed(() => activeSport.value?.id === 'baseball'
  ? sportNavigation.baseball
  : activeSport.value ? (sportNavigation[activeSport.value.id] || sportNavigation.default)(activeSport.value) : [['Platform', '/'], ['All-sports builder', '/build']])
const isBaseball = computed(() => activeSport.value?.id === 'baseball')
const isNavActive = path => route.path === path || (
  path !== '/' && path !== activeSport.value?.route && route.path.startsWith(`${path}/`)
)
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
    <aside class="sport-rail" :class="{ open:sportOpen }">
      <RouterLink to="/" class="rail-brand" aria-label="NINTH all sports"><img src="/brand/ninth-icon-192.png" alt="NINTH logo"><span>NINTH</span></RouterLink>
      <nav aria-label="Sport workspaces">
        <RouterLink v-for="sport in sports" :key="sport.id" :to="sport.route" :class="{active:sport.id===sportId}" :style="{'--sport':sport.accent}" :title="sport.name">
          <component :is="icons[sport.id]" :size="19"/><span>{{ sport.short }}</span><i></i>
        </RouterLink>
      </nav>
      <button class="theme-toggle" type="button" :aria-label="store.theme === 'dark' ? 'Use light theme' : 'Use dark theme'" @click="store.toggleTheme()"><span>{{ store.theme === 'dark' ? 'N' : 'D' }}</span><small>MODE</small></button>
    </aside>

    <div class="workspace-shell">
      <header class="workspace-header">
        <div class="header-row">
          <button class="sport-menu" type="button" aria-label="Choose sport" @click="sportOpen=!sportOpen"><X v-if="sportOpen"/><Menu v-else/></button>
          <RouterLink to="/" class="mobile-brand"><img src="/brand/ninth-icon-192.png" alt="NINTH logo"><b>NINTH</b></RouterLink>
          <div class="workspace-title">
            <small>{{ activeSport ? activeSport.eyebrow : 'DECISION SYSTEM' }}</small>
            <b>{{ activeSport ? activeSport.name : 'All sports' }}</b>
            <em v-if="activeSport">{{ activeSport.status === 'live' ? 'PRODUCTION' : 'RESEARCH LAB' }}</em>
          </div>
          <nav class="context-nav" :class="{open:navOpen}" aria-label="Workspace navigation">
            <RouterLink v-for="item in nav" :key="item[1]" :to="item[1]" :class="{active:isNavActive(item[1])}">{{ item[0] }}</RouterLink>
          </nav>
          <form v-if="isBaseball" ref="searchRoot" class="search" @submit.prevent="go">
            <Search :size="15"/><input v-model="query" placeholder="Search MLB" autocomplete="off" aria-label="Search MLB" @focus="focused=true">
            <div v-if="focused && query.trim().length >= 2" class="search-menu">
              <span v-if="searching" class="search-state">SEARCHING OFFICIAL MLB DATA…</span>
              <template v-else-if="quickResults.length"><button v-for="item in quickResults" :key="item.group+item.path" type="button" @pointerdown.prevent="pickResult(item)"><TeamLogo v-if="item.group==='Teams'" :team="item" :size="34"/><PlayerHeadshot v-else-if="item.group==='Players'" :id="item.id" :name="item.name" :size="34"/><i v-else>{{ item.abbr }}</i><span><b>{{ item.name }}</b><small>{{ item.detail }}</small></span></button></template>
              <span v-else class="search-state">NO MATCHES IN OFFICIAL MLB DATA</span>
            </div>
          </form>
          <button v-if="nav.length" class="nav-menu" type="button" aria-label="Open workspace navigation" @click="navOpen=!navOpen"><X v-if="navOpen"/><Menu v-else/></button>
        </div>
        <div v-if="isBaseball" class="score-strip"><span class="strip-label"><i :class="{'live-dot':store.dashboard?.live?.length}"></i>{{ store.dashboard?.live?.length ? 'LIVE MLB' : 'TODAY' }}</span><RouterLink v-for="game in tickerGames" :key="game.id" :to="gamePath(game)"><b>{{ game.away.abbr }}</b><em>{{ game.away.score }}</em><span>—</span><em>{{ game.home.score }}</em><b>{{ game.home.abbr }}</b><small>{{ tickerState(game) }}</small></RouterLink><span v-if="!tickerGames.length" class="empty-strip">Official scoreboard syncing</span><span class="feed-state"><i></i> FEEDS CONNECTED</span></div>
      </header>
      <main><div class="content"><slot/></div></main>
    </div>
  </div>
</template>

<style scoped>
.app-shell{min-height:100vh;--rail:78px;--workspace-accent:var(--accent)}.sport-rail{position:fixed;inset:0 auto 0 0;width:var(--rail);z-index:60;display:flex;flex-direction:column;align-items:center;background:var(--contrast);color:var(--on-contrast);border-right:1px solid #2c322b}.rail-brand{height:74px;width:100%;display:grid;place-items:center;text-decoration:none;border-bottom:1px solid #2c322b}.rail-brand img{width:31px;height:31px}.rail-brand span{display:none}.sport-rail nav{width:100%;display:grid;padding:14px 0}.sport-rail nav a{height:59px;display:grid;place-items:center;align-content:center;gap:5px;position:relative;text-decoration:none;color:#8e968b}.sport-rail nav a span{font:700 6px 'DM Mono';letter-spacing:.08em}.sport-rail nav a i{position:absolute;right:0;top:11px;bottom:11px;width:3px;background:var(--sport);transform:scaleY(0);transition:transform .18s}.sport-rail nav a:hover,.sport-rail nav a.active{color:var(--sport);background:#151a15}.sport-rail nav a.active i{transform:scaleY(1)}.theme-toggle{margin:auto 0 15px;width:48px;height:48px;border:1px solid #353c34;background:#151a15;color:var(--on-contrast);display:grid;place-items:center;align-content:center;gap:2px;cursor:pointer}.theme-toggle span{font:800 13px 'DM Mono';color:var(--accent)}.theme-toggle small{font:600 5px 'DM Mono';color:#899186}.workspace-shell{min-height:100vh;margin-left:var(--rail)}.workspace-header{position:sticky;top:0;z-index:40;background:color-mix(in srgb,var(--paper) 94%,transparent);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}.header-row{height:74px;max-width:1600px;margin:auto;padding:0 25px;display:flex;align-items:center;gap:24px}.workspace-title{width:184px;display:grid;grid-template-columns:1fr auto;align-items:end;gap:2px 8px;flex:none}.workspace-title small{grid-column:1/-1;font:600 6px 'DM Mono';letter-spacing:.12em;color:var(--muted)}.workspace-title b{overflow:hidden;font-size:17px;letter-spacing:-.04em;text-overflow:ellipsis;white-space:nowrap}.workspace-title em{padding:4px 5px;background:color-mix(in srgb,var(--workspace-accent) 16%,transparent);color:var(--workspace-accent);font:700 5px 'DM Mono';font-style:normal}.context-nav{display:flex;align-items:center;gap:2px;min-width:0}.context-nav a{height:38px;padding:0 10px;display:flex;align-items:center;text-decoration:none;color:var(--muted);font-size:9px;font-weight:700;white-space:nowrap;border-bottom:2px solid transparent}.context-nav a:hover,.context-nav a.active{color:var(--text);border-color:var(--workspace-accent);background:color-mix(in srgb,var(--workspace-accent) 8%,transparent)}.search{position:relative;margin-left:auto;width:190px;height:35px;display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--text)}.search input{width:100%;min-width:0;border:0;outline:0;background:transparent;color:var(--text);font-size:9px}.search-menu{position:absolute;right:0;top:43px;width:380px;padding:6px;background:var(--surface);border:1px solid var(--ink);box-shadow:var(--shadow)}.search-menu button{width:100%;padding:8px;display:flex;align-items:center;gap:9px;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--text);text-align:left;cursor:pointer}.search-menu button:hover{background:var(--wash)}.search-menu button>span{display:grid;gap:2px}.search-menu b{font-size:10px}.search-menu small{font-size:7px;color:var(--muted)}.search-menu button>i{width:34px;font:700 7px 'DM Mono';font-style:normal}.search-state{display:block;padding:18px 10px;font:600 7px 'DM Mono';color:var(--muted)}.score-strip{height:37px;display:flex;align-items:center;gap:24px;padding:0 max(25px,calc((100vw - var(--rail) - 1510px)/2));overflow:hidden;white-space:nowrap;background:var(--contrast);color:var(--on-contrast)}.strip-label{display:flex;align-items:center;gap:7px;font:600 7px 'DM Mono';color:var(--accent)}.strip-label>i:not(.live-dot){width:6px;height:6px;background:var(--accent);border-radius:50%}.score-strip a{display:flex;align-items:center;gap:7px;text-decoration:none;font:500 8px 'DM Mono'}.score-strip a em{font-style:normal;color:var(--accent)}.score-strip a small{color:#949b91;margin-left:3px}.feed-state{margin-left:auto;font:600 6px 'DM Mono';color:#8f968b}.feed-state i{display:inline-block;width:5px;height:5px;margin-right:5px;background:var(--accent);border-radius:50%}.empty-strip{font:7px 'DM Mono';color:#999}.content{max-width:1560px;margin:auto;padding:0 25px 48px}.sport-menu,.nav-menu,.mobile-brand{display:none}
@media(max-width:1250px){.context-nav{display:none;position:absolute;top:74px;left:0;right:0;padding:10px 20px;background:var(--surface);border-bottom:1px solid var(--line);flex-wrap:wrap}.context-nav.open{display:flex}.context-nav a{height:42px;border:1px solid var(--line)}.nav-menu{display:grid;place-items:center;margin-left:auto;border:0;background:transparent;color:var(--text);cursor:pointer}.search{margin-left:0}.workspace-title{width:auto;min-width:170px}}
@media(max-width:760px){.app-shell{--rail:0}.workspace-shell{margin:0}.sport-rail{width:245px;align-items:stretch;transform:translateX(-100%);transition:transform .2s;box-shadow:20px 0 60px rgba(0,0,0,.35)}.sport-rail.open{transform:translateX(0)}.rail-brand{display:flex;justify-content:flex-start;gap:10px;padding:0 18px}.rail-brand span{display:block;font-weight:900}.sport-rail nav a{height:54px;grid-template-columns:28px 1fr;justify-items:start;align-content:center;padding:0 18px}.sport-rail nav a span{font-size:8px}.theme-toggle{margin:auto 18px 18px}.header-row{height:62px;padding:0 13px;gap:12px}.sport-menu,.mobile-brand{display:flex;align-items:center;border:0;background:transparent;color:var(--text)}.sport-menu{padding:0}.mobile-brand{gap:7px;text-decoration:none}.mobile-brand img{width:29px;height:29px}.mobile-brand b{font-size:15px}.workspace-title{display:none}.context-nav{top:62px;padding:8px}.context-nav a{flex:1;min-width:110px;justify-content:center}.search{margin-left:auto;width:115px}.search-menu{position:fixed;left:8px;right:8px;top:68px;width:auto}.score-strip{height:35px;padding:0 13px}.feed-state{display:none}.content{padding:0 13px 42px}.nav-menu{margin-left:0}}
@media(max-width:470px){.search{display:none}.mobile-brand{margin-right:auto}}
</style>
