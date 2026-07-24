<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CalendarDays, Radio, Shield, Users, BrainCircuit, FileText, Search, Menu, X, Trophy, ListPlus } from 'lucide-vue-next'
import { useAppStore } from '../../stores/app'
import { api } from '../../services/api'
import TeamLogo from '../team/TeamLogo.vue'
import PlayerHeadshot from '../player/PlayerHeadshot.vue'

const store = useAppStore()
const router = useRouter()
const route = useRoute()
const query = ref('')
const open = ref(false)
const searchOpen = ref(false)
const focused = ref(false)
const searching = ref(false)
const searchResults = ref({ Teams: [], Players: [], Games: [] })
const searchRoot = ref()
const nav = [['Games','/schedule',CalendarDays],['Live','/live',Radio],['Builder','/builder',ListPlus],['Standings','/standings',Trophy],['Teams','/teams',Shield],['Players','/players',Users],['Model','/model',BrainCircuit],['My slips','/slips',FileText]]
const isNavActive = path => {
  if (path === '/builder') return route.path === '/builder' || route.path === '/props-builder'
  if (['/live', '/teams', '/players'].includes(path)) return route.path === path || route.path.startsWith(`${path}/`)
  return route.path === path
}
const tickerGames = computed(() => (store.dashboard?.live?.length ? store.dashboard.live : store.dashboard?.today?.length ? store.dashboard.today : store.dashboard?.completed || []).slice(0, 4))
const quickResults = computed(() => Object.entries(searchResults.value).flatMap(([group, items]) => (items || []).slice(0, 4).map(item => ({ ...item, group }))).slice(0, 9))
const gamePath = game => /live|progress|delay/i.test(game.status || '') ? `/live/${game.id}` : `/games/${game.id}`
const tickerState = game => /live|progress|delay/i.test(game.status || '') ? (game.inning || game.status) : game.status
const go = () => { if (query.value.trim()) { router.push({ path: '/search', query: { q: query.value.trim() } }); searchOpen.value = false; focused.value = false } }
const pickResult = item => { router.push(item.path); query.value = ''; searchOpen.value = false; focused.value = false }
const closeSearchOutside = event => { if (!searchRoot.value?.contains(event.target)) { focused.value = false; searchOpen.value = false } }

let searchTimer
watch(query, value => {
  clearTimeout(searchTimer)
  const term = value.trim()
  if (term.length < 2) { searchResults.value = { Teams: [], Players: [], Games: [] }; searching.value = false; return }
  searching.value = true
  searchTimer = setTimeout(async () => {
    try { searchResults.value = await api.search(term) }
    catch { searchResults.value = { Teams: [], Players: [], Games: [] } }
    finally { searching.value = false }
  }, 240)
})
onMounted(() => document.addEventListener('pointerdown', closeSearchOutside))
onBeforeUnmount(() => { clearTimeout(searchTimer); document.removeEventListener('pointerdown', closeSearchOutside) })
</script>

<template>
  <div class="app-shell">
    <header>
      <div class="header-row">
        <RouterLink to="/" class="brand"><img src="/brand/ninth-icon-192.png" alt="NINTH logo"><span><b>NINTH</b><small>BASEBALL / DECISION LAB</small></span></RouterLink>
        <nav :class="{ open }"><RouterLink v-for="item in nav" :key="item[1]" :to="item[1]" :class="{ 'section-active': isNavActive(item[1]) }" @click="open=false"><component :is="item[2]" :size="15"/><span>{{ item[0] }}</span></RouterLink></nav>
        <form ref="searchRoot" :class="['search', { open: searchOpen }]" @submit.prevent="go">
          <Search :size="15"/>
          <input v-model="query" placeholder="Search teams, players, games" autocomplete="off" aria-label="Search MLB" @focus="focused=true">
          <button type="button" class="close-search" @click="searchOpen=false"><X :size="15"/></button>
          <div v-if="focused && query.trim().length >= 2" class="search-menu">
            <span v-if="searching" class="search-state">SEARCHING OFFICIAL MLB DATA…</span>
            <template v-else-if="quickResults.length">
              <button v-for="item in quickResults" :key="item.group+item.path" type="button" @pointerdown.prevent="pickResult(item)"><TeamLogo v-if="item.group==='Teams'" :team="item" :size="38"/><PlayerHeadshot v-else-if="item.group==='Players'" :id="item.id" :name="item.name" :size="38"/><i v-else>{{ item.abbr }}</i><span><b>{{ item.name }}</b><small>{{ item.detail }}</small></span><em>OPEN →</em></button>
              <button type="submit" class="all-results"><span>View all results for “{{ query.trim() }}”</span><em>→</em></button>
            </template>
            <span v-else class="search-state">NO MATCHES IN OFFICIAL MLB DATA</span>
          </div>
        </form>
        <button :class="['theme-toggle', store.theme]" type="button" :aria-label="store.theme === 'dark' ? 'Use light theme' : 'Use dark theme'" :title="store.theme === 'dark' ? 'Switch display to day mode' : 'Switch display to night mode'" @click="store.toggleTheme()"><span class="theme-copy"><small>DISPLAY / 09</small><b>{{ store.theme === 'dark' ? 'NIGHT' : 'DAY' }}</b></span><span class="theme-signal" aria-hidden="true"><i></i><i></i><i></i></span></button>
        <button class="search-toggle" @click="searchOpen=!searchOpen" aria-label="Search"><Search :size="18"/></button>
        <button class="menu" @click="open=!open" aria-label="Menu"><X v-if="open"/><Menu v-else/></button>
      </div>
      <div class="score-strip"><span class="strip-label"><i :class="{'live-dot':store.dashboard?.live?.length}"></i>{{ store.dashboard?.live?.length ? 'LIVE MLB' : 'TODAY' }}</span><RouterLink v-for="game in tickerGames" :key="game.id" :to="gamePath(game)"><b>{{ game.away.abbr }}</b><em>{{ game.away.score }}</em><span>—</span><em>{{ game.home.score }}</em><b>{{ game.home.abbr }}</b><small>{{ tickerState(game) }}</small></RouterLink><span v-if="!tickerGames.length" class="empty-strip">Official scoreboard syncing</span><span class="feed-state"><i></i> OFFICIAL FEEDS CONNECTED</span></div>
    </header>
    <main><div class="content"><slot/></div></main>
    <div class="mobile-nav"><RouterLink v-for="item in nav.slice(0,5)" :key="item[1]" :to="item[1]" :class="{ 'section-active': isNavActive(item[1]) }"><component :is="item[2]" :size="19"/><small>{{ item[0] }}</small></RouterLink></div>
  </div>
</template>

<style scoped>
.app-shell{min-height:100vh}header{position:sticky;top:0;z-index:40;background:color-mix(in srgb,var(--paper) 94%,transparent);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}.header-row{height:72px;max-width:1560px;margin:auto;padding:0 25px;display:flex;align-items:center;gap:28px}.brand{display:flex;align-items:center;gap:10px;text-decoration:none;flex:none}.brand img{width:36px;height:36px;border-radius:3px}.brand span{display:flex;flex-direction:column}.brand b{font-size:20px;letter-spacing:-.065em;line-height:1}.brand small{font:500 6px 'DM Mono';letter-spacing:.14em;color:var(--muted);margin-top:5px}nav{display:flex;align-items:center;gap:4px;margin-left:20px}nav a{height:38px;display:flex;align-items:center;gap:7px;padding:0 11px;text-decoration:none;font-size:10px;font-weight:650;color:var(--muted);border-bottom:2px solid transparent}nav a:hover{color:var(--text)}nav a.router-link-exact-active{color:var(--text);border-color:var(--ink)}
.search{position:relative;margin-left:auto;width:245px;height:36px;border-bottom:1px solid var(--ink);display:flex;align-items:center;gap:8px}.search input{min-width:0;width:100%;border:0;outline:0;background:transparent;font-size:10px;color:var(--text)}.close-search,.search-toggle,.menu{display:none;border:0;background:transparent}.theme-toggle{width:108px;height:42px;display:flex;align-items:center;justify-content:space-between;gap:10px;flex:none;position:relative;padding:0 10px 0 13px;border:1px solid var(--line);border-radius:0;background:var(--surface);color:var(--text);cursor:pointer;overflow:hidden;transition:border-color .16s,background .16s}.theme-toggle:before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--acid)}.theme-toggle:hover{border-color:var(--acid);background:var(--wash)}.theme-copy{display:flex;flex-direction:column;align-items:flex-start;gap:3px}.theme-copy small{font:500 5px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.theme-copy b{font:800 9px 'DM Mono';letter-spacing:.12em}.theme-signal{height:23px;display:flex;align-items:flex-end;gap:3px;padding-left:8px;border-left:1px solid var(--line)}.theme-signal i{display:block;width:3px;background:var(--muted);transition:height .2s,background .2s}.theme-signal i:nth-child(1){height:7px}.theme-signal i:nth-child(2){height:12px}.theme-signal i:nth-child(3){height:18px;background:var(--acid)}.theme-toggle.light .theme-signal{align-items:center}.theme-toggle.light .theme-signal i{height:14px;background:var(--orange)}.theme-toggle.light .theme-signal i:nth-child(2){height:20px;background:var(--accent)}.search-menu{position:absolute;right:0;top:43px;width:430px;padding:7px;background:var(--surface);border:1px solid var(--ink);box-shadow:var(--shadow);z-index:50}.search-menu button{width:100%;display:flex;align-items:center;gap:10px;padding:10px;border:0;border-bottom:1px solid var(--line);background:transparent;text-align:left;color:var(--text);cursor:pointer}.search-menu button:hover,.search-menu button:focus{background:var(--accent);color:#151812;outline:0}.search-menu i{width:53px;font:600 7px 'DM Mono';font-style:normal;letter-spacing:.08em;color:var(--muted)}.search-menu button>span{min-width:0;display:flex;flex:1;flex-direction:column}.search-menu b{font-size:11px}.search-menu small{margin-top:3px;font-size:8px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.search-menu em{font:600 7px 'DM Mono';font-style:normal;color:var(--muted)}.search-menu .all-results{border-bottom:0;margin-top:2px}.search-state{display:block;padding:18px 12px;font:500 8px 'DM Mono';color:var(--muted)}
.score-strip{height:39px;border-top:1px solid var(--line);display:flex;align-items:center;gap:24px;padding:0 max(25px,calc((100vw - 1510px)/2));overflow:hidden;white-space:nowrap;background:var(--ink);color:var(--paper)}.strip-label{display:flex;align-items:center;gap:7px;font:500 8px 'DM Mono';color:var(--accent)}.strip-label>i:not(.live-dot){width:6px;height:6px;background:var(--accent);border-radius:50%}.score-strip a{display:flex;align-items:center;gap:7px;text-decoration:none;font:500 9px 'DM Mono'}.score-strip a b{font-size:9px}.score-strip a em{font-style:normal;color:var(--accent)}.score-strip a span{color:#62675e}.score-strip a small{color:#9b9f97;margin-left:3px}.feed-state{margin-left:auto;font:500 7px 'DM Mono';color:#90958c}.feed-state i{display:inline-block;width:5px;height:5px;background:var(--accent);border-radius:50%;margin-right:5px}.empty-strip{font:8px 'DM Mono';color:#999}.content{max-width:1510px;margin:auto;padding:0 25px 45px}.mobile-nav{display:none}.menu{cursor:pointer}
@media(max-width:1050px){.header-row{gap:14px}nav{margin-left:5px}nav a{padding:0 8px}nav a svg{display:none}.search{width:190px}}
@media(max-width:760px){header{top:0}.header-row{height:60px;padding:0 13px}.brand img{width:32px;height:32px}.brand b{font-size:17px}.brand small{font-size:5px}nav{display:none;position:absolute;top:60px;left:0;right:0;margin:0;padding:10px;background:var(--surface);border-bottom:1px solid var(--line);grid-template-columns:1fr 1fr}nav.open{display:grid}nav a{height:48px;border:1px solid var(--line)}nav a svg{display:block}.search{display:none;position:absolute;left:0;right:0;top:60px;width:auto;height:52px;padding:0 15px;background:var(--surface);border:1px solid var(--line);z-index:5}.search.open{display:flex}.search-menu{position:fixed;left:8px;right:8px;top:117px;width:auto;max-height:calc(100vh - 198px);overflow:auto}.close-search{display:grid}.search-toggle,.menu{display:grid;place-items:center}.search-toggle{margin-left:auto}.menu{margin-left:0}.theme-toggle{width:75px;height:36px;padding:0 7px 0 10px;gap:6px}.theme-copy small{display:none}.theme-copy b{font-size:8px}.theme-signal{height:19px;gap:2px;padding-left:6px}.theme-signal i{width:2px}.theme-signal i:nth-child(3){height:15px}.score-strip{height:36px;padding:0 13px;gap:18px}.feed-state{display:none}.content{padding:0 13px 78px}.mobile-nav{position:fixed;display:flex;bottom:0;left:0;right:0;height:63px;background:var(--surface);border-top:1px solid var(--line);z-index:35}.mobile-nav a{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;text-decoration:none;color:var(--muted)}.mobile-nav a.router-link-exact-active{color:#151812;background:var(--accent)}.mobile-nav small{font-size:7px}}
.search-menu button>i{width:38px;height:38px;display:grid;place-items:center;flex:none;background:var(--wash);font:600 7px 'DM Mono';font-style:normal;letter-spacing:.03em;color:var(--muted);text-align:center}.search-menu button>.team-logo,.search-menu button>.headshot{flex:none}.search-menu button{padding:9px}.header-row nav a{height:42px;padding:0 13px;font-size:11px;gap:8px}.score-strip{background:var(--contrast);color:var(--on-contrast)}
.header-row nav a.section-active{color:var(--text);border-color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent)}
@media(max-width:760px){.mobile-nav a.section-active{color:#151812;background:var(--accent)}}
</style>
