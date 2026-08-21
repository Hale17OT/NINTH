import { createRouter, createWebHistory } from 'vue-router'
import PlatformHomeView from '../views/PlatformHomeView.vue'
import { useAuthStore } from '../features/auth/stores/auth'
import { safeReturnTo } from '../features/auth/utils/returnTo.js'

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
const SignInView = () => import('../features/auth/views/SignInView.vue')
const SignUpView = () => import('../features/auth/views/SignUpView.vue')
const ForgotPasswordView = () => import('../features/auth/views/ForgotPasswordView.vue')
const ResetPasswordView = () => import('../features/auth/views/ResetPasswordView.vue')
const VerifyEmailView = () => import('../features/auth/views/VerifyEmailView.vue')
const OAuthCallbackView = () => import('../features/auth/views/OAuthCallbackView.vue')
const AccountView = () => import('../views/account/AccountView.vue')
const SavedView = () => import('../views/account/SavedView.vue')
const LegalView = () => import('../views/account/LegalView.vue')

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
  { path: '/auth/sign-in', component: SignInView, meta: { sport: 'platform', authLayout: true, guestOnly: true } },
  { path: '/auth/sign-up', component: SignUpView, meta: { sport: 'platform', authLayout: true, guestOnly: true } },
  { path: '/auth/forgot-password', component: ForgotPasswordView, meta: { sport: 'platform', authLayout: true, guestOnly: true } },
  { path: '/auth/reset-password', component: ResetPasswordView, meta: { sport: 'platform', authLayout: true } },
  { path: '/auth/verify-email', component: VerifyEmailView, meta: { sport: 'platform', authLayout: true } },
  { path: '/auth/callback', component: OAuthCallbackView, meta: { sport: 'platform', authLayout: true } },
  { path: '/account', component: AccountView, meta: { sport: 'platform', requiresAuth: true } },
  { path: '/saved', component: SavedView, meta: { sport: 'platform', requiresAuth: true } },
  { path: '/legal/terms', component: LegalView, props: { type: 'terms' }, meta: { sport: 'platform' } },
  { path: '/legal/privacy', component: LegalView, props: { type: 'privacy' }, meta: { sport: 'platform' } },
  { path: '/build', component: MultiSportBuilderView, meta: { sport: 'platform', requiresAuth: true } },
  { path: '/american-football/builder', component: () => import('../views/NflBuilderView.vue'), meta: { sport: 'american-football', requiresAuth: true } },
  { path: '/football/builder', component: CompetitionBuilderView, props: { sport: 'football' }, meta: { sport: 'football', requiresAuth: true } },
  { path: '/esports/builder', component: CompetitionBuilderView, props: { sport: 'esports' }, meta: { sport: 'esports', requiresAuth: true } },
  { path: '/basketball/builder', component: () => import('../views/NbaBuilderView.vue'), meta: { sport: 'basketball', requiresAuth: true } },
  { path: '/baseball', component: HomeView, meta: baseball },
  { path: '/baseball/guarantees', component: () => import('../views/GuaranteeListView.vue'), meta: baseball },
  ...sportRoutes,
  { path: '/valorant/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/cs2/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/lol/:pathMatch(.*)*', redirect: esportsRedirect },
  { path: '/builder', component: () => import('../views/SlipBuilderView.vue'), meta: baseball },
  { path: '/props-builder', component: () => import('../views/PlayerPropsBuilderView.vue'), meta: { ...baseball, requiresAuth: true } },
  { path: '/slips', redirect: '/baseball' },
  { path: '/alter-ego', component: () => import('../views/AlterEgoView.vue'), meta: { ...baseball, requiresAuth: true } },
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
router.beforeEach(async to => {
  const auth = useAuthStore()
  if (!auth.hydrated) await auth.hydrate()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { path: '/auth/sign-in', query: { returnTo: safeReturnTo(to.fullPath) } }
  }
  if (to.meta.guestOnly && auth.isAuthenticated) return typeof to.query.returnTo === 'string' ? safeReturnTo(to.query.returnTo) : '/account'
})
router.afterEach(to => {
  const labels = {
    platform: 'Multi-Sport Decision System', baseball: 'Baseball Decision Lab',
    football: 'Football Research Lab', 'american-football': 'American Football Research Lab',
    basketball: 'NBA Research Lab', esports: 'Esports Research Lab',
  }
  document.title = `NINTH · ${labels[to.meta?.sport] || 'Decision System'}`
})
export default router
