import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import GameView from '../views/GameView.vue'
import LiveView from '../views/LiveView.vue'
import LiveCenterView from '../views/LiveCenterView.vue'
import SlipsView from '../views/SlipsView.vue'
import EntityView from '../views/EntityView.vue'
import ExplorerView from '../views/ExplorerView.vue'
import SearchView from '../views/SearchView.vue'
import TeamsView from '../views/TeamsView.vue'
import PlayersView from '../views/PlayersView.vue'
import ModelView from '../views/ModelView.vue'
import StandingsView from '../views/StandingsView.vue'
import NotFoundView from '../views/NotFoundView.vue'
import PlatformHomeView from '../views/PlatformHomeView.vue'
import SportHubView from '../views/SportHubView.vue'
import SportDirectoryView from '../views/SportDirectoryView.vue'
import MultiSportBuilderView from '../views/MultiSportBuilderView.vue'

const baseball = { sport: 'baseball' }
const sportRoutes = ['football', 'american-football', 'basketball', 'esports'].flatMap(sport => [
  { path: `/${sport}`, component: SportHubView, props: { sport }, meta: { sport } },
  ...['leagues', 'games', 'teams', 'players'].map(type => ({
    path: `/${sport}/${type}`, component: SportDirectoryView, props: { sport, type }, meta: { sport },
  })),
  { path: `/${sport}/models`, component: SportHubView, props: { sport, section: 'models' }, meta: { sport } },
  { path: `/${sport}/data`, component: SportHubView, props: { sport, section: 'data' }, meta: { sport } },
])

const esportsRedirect = to => `/esports${to.params.pathMatch?.length ? `/${to.params.pathMatch.join('/')}` : ''}`
const routes = [
  { path: '/', component: PlatformHomeView, meta: { sport: 'platform' } },
  { path: '/build', component: MultiSportBuilderView, meta: { sport: 'platform' } },
  { path: '/american-football/builder', component: () => import('../views/NflBuilderView.vue'), meta: { sport: 'american-football' } },
  { path: '/baseball', component: HomeView, meta: baseball },
  { path: '/baseball/guarantees', component: () => import('../views/GuaranteeListView.vue'), meta: baseball },
  ...sportRoutes,
  { path: '/valorant/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/cs2/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/lol/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/builder', component: () => import('../views/SlipBuilderView.vue'), meta: baseball },
  { path: '/props-builder', component: () => import('../views/PlayerPropsBuilderView.vue'), meta: baseball },
  { path: '/slips', component: SlipsView, meta: baseball },
  { path: '/alter-ego', component: () => import('../views/AlterEgoView.vue'), meta: baseball },
  { path: '/games/:id', component: GameView, meta: baseball },
  { path: '/live', component: LiveCenterView, meta: baseball },
  { path: '/live/:id', component: LiveView, meta: baseball },
  { path: '/teams', component: TeamsView, meta: baseball },
  { path: '/teams/:id', component: EntityView, props: { type: 'team' }, meta: baseball },
  { path: '/players', component: PlayersView, meta: baseball },
  { path: '/players/:id', component: EntityView, props: { type: 'player' }, meta: baseball },
  { path: '/standings', component: StandingsView, meta: baseball },
  { path: '/model', component: ModelView, meta: baseball },
  { path: '/betting', redirect: '/model' },
  { path: '/schedule', component: ExplorerView, props: { type: 'schedule' }, meta: baseball },
  { path: '/search', component: SearchView, meta: baseball },
  { path: '/:pathMatch(.*)*', component: NotFoundView },
]

const router = createRouter({ history: createWebHistory(), routes, scrollBehavior: () => ({ top: 0 }) })
router.afterEach(to => {
  const labels = {
    platform: 'Multi-Sport Decision System', baseball: 'Baseball Decision Lab',
    football: 'Football Research Lab', 'american-football': 'American Football Research Lab',
    basketball: 'Basketball Research Lab', esports: 'Esports Research Lab',
  }
  document.title = `NINTH · ${labels[to.meta?.sport] || 'Decision System'}`
})
export default router
