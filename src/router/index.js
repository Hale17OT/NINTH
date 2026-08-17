import { createRouter, createWebHistory } from 'vue-router'
import PlatformHomeView from '../views/PlatformHomeView.vue'

const HomeView = () => import('../views/HomeView.vue')
const GameView = () => import('../views/GameView.vue')
const LiveView = () => import('../views/LiveView.vue')
const LiveCenterView = () => import('../views/LiveCenterView.vue')
const EntityView = () => import('../views/EntityView.vue')
const ExplorerView = () => import('../views/ExplorerView.vue')
const SearchView = () => import('../views/SearchView.vue')
const TeamsView = () => import('../views/TeamsView.vue')
const PlayersView = () => import('../views/PlayersView.vue')
const ModelView = () => import('../views/ModelView.vue')
const StandingsView = () => import('../views/StandingsView.vue')
const NotFoundView = () => import('../views/NotFoundView.vue')
const SportHubView = () => import('../views/SportHubView.vue')
const SportDirectoryView = () => import('../views/SportDirectoryView.vue')
const MultiSportBuilderView = () => import('../views/MultiSportBuilderView.vue')
const SportLeagueView = () => import('../views/SportLeagueView.vue')
const SportTeamView = () => import('../views/SportTeamView.vue')
const SportPlayerView = () => import('../views/SportPlayerView.vue')
const SportMatchView = () => import('../views/SportMatchView.vue')
const CompetitionBuilderView = () => import('../views/CompetitionBuilderView.vue')

const baseball = { sport: 'baseball' }
const sportRoutes = ['football', 'american-football', 'basketball', 'esports'].flatMap(sport => [
  { path: `/${sport}`, component: SportHubView, props: { sport }, meta: { sport } },
  ...['leagues', 'games', 'teams', 'players'].map(type => ({
    path: `/${sport}/${type}`, component: SportDirectoryView, props: { sport, type }, meta: { sport },
  })),
  { path: `/${sport}/models`, component: SportHubView, props: { sport, section: 'models' }, meta: { sport } },
  { path: `/${sport}/data`, component: SportHubView, props: { sport, section: 'data' }, meta: { sport } },
  { path: `/${sport}/leagues/:id`, component: SportLeagueView, props: { sport }, meta: { sport } },
  { path: `/${sport}/teams/:id`, component: SportTeamView, props: { sport }, meta: { sport } },
  { path: `/${sport}/players/:id`, component: SportPlayerView, props: { sport }, meta: { sport } },
  { path: `/${sport}/games/:id`, component: SportMatchView, props: { sport }, meta: { sport } },
])

const esportsRedirect = to => `/esports${to.params.pathMatch?.length ? `/${to.params.pathMatch.join('/')}` : ''}`
const routes = [
  { path: '/', component: PlatformHomeView, meta: { sport: 'platform' } },
  { path: '/build', component: MultiSportBuilderView, meta: { sport: 'platform' } },
  { path: '/american-football/builder', component: () => import('../views/NflBuilderView.vue'), meta: { sport: 'american-football' } },
  { path: '/football/builder', component: CompetitionBuilderView, props: { sport: 'football' }, meta: { sport: 'football' } },
  { path: '/esports/builder', component: CompetitionBuilderView, props: { sport: 'esports' }, meta: { sport: 'esports' } },
  { path: '/basketball/builder', component: () => import('../views/NbaBuilderView.vue'), meta: { sport: 'basketball' } },
  { path: '/baseball', component: HomeView, meta: baseball },
  { path: '/baseball/guarantees', component: () => import('../views/GuaranteeListView.vue'), meta: baseball },
  ...sportRoutes,
  { path: '/valorant/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/cs2/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/lol/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/builder', component: () => import('../views/SlipBuilderView.vue'), meta: baseball },
  { path: '/props-builder', component: () => import('../views/PlayerPropsBuilderView.vue'), meta: baseball },
  { path: '/slips', redirect: '/baseball' },
  { path: '/alter-ego', component: () => import('../views/AlterEgoView.vue'), meta: baseball },
  { path: '/games/:id', component: GameView, meta: baseball },
  { path: '/live', component: LiveCenterView, meta: baseball },
  { path: '/live/:id', component: LiveView, meta: baseball },
  { path: '/teams', component: TeamsView, meta: baseball },
  { path: '/compare', redirect: '/baseball' },
  { path: '/teams/:id', component: EntityView, props: { type: 'team' }, meta: baseball },
  { path: '/players', component: PlayersView, meta: baseball },
  { path: '/players/:id', component: EntityView, props: { type: 'player' }, meta: baseball },
  { path: '/standings', component: StandingsView, meta: baseball },
  { path: '/model', component: ModelView, meta: baseball },
  { path: '/betting', redirect: '/model' },
  { path: '/schedule', component: ExplorerView, props: { type: 'schedule' }, meta: baseball },
  { path: '/search', component: SearchView, meta: baseball },
  { path: '/experiments/visual-qa', component: () => import('../views/VisualQaView.vue'), meta: { sport: 'platform' } },
  { path: '/:pathMatch(.*)*', component: NotFoundView },
]

const router = createRouter({ history: createWebHistory(), routes, scrollBehavior: () => ({ top: 0 }) })
router.afterEach(to => {
  const labels = {
    platform: 'Multi-Sport Decision System', baseball: 'Baseball Decision Lab',
    football: 'Football Research Lab', 'american-football': 'American Football Research Lab',
    basketball: 'NBA Research Lab', esports: 'Esports Research Lab',
  }
  document.title = `NINTH · ${labels[to.meta?.sport] || 'Decision System'}`
})
export default router
