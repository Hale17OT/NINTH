export const sports = [
  {
    id: 'baseball', name: 'Baseball', short: 'MLB', route: '/baseball', status: 'live',
    eyebrow: 'PRODUCTION', accent: '#c7f04b', numeral: '01',
    description: 'Pregame, live, totals and player-prop intelligence with immutable audits.',
    leagues: ['MLB'],
  },
  {
    id: 'football', name: 'Football', short: 'FTB', route: '/football', status: 'research',
    eyebrow: 'TOP FIVE LEAGUES', accent: '#36d5b3', numeral: '02',
    description: 'Scoreline distributions, xG-adjusted team strength and lineup-aware markets.',
    leagues: ['Premier League', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1'],
  },
  {
    id: 'american-football', name: 'American Football', short: 'NFL', route: '/american-football', status: 'research',
    eyebrow: 'NFL', accent: '#83a8ff', numeral: '03',
    description: 'EPA, success rate, quarterback value, injuries and drive-level simulation.',
    leagues: ['NFL'],
  },
  {
    id: 'basketball', name: 'NBA', short: 'NBA', route: '/basketball', status: 'research',
    eyebrow: 'NBA', accent: '#f6b945', numeral: '04',
    description: 'Possession forecasts, lineup impact, rest, availability and pace distributions.',
    leagues: ['NBA'],
  },
  {
    id: 'esports', name: 'Esports', short: 'ESP', route: '/esports', status: 'research',
    eyebrow: 'VALORANT + CS2 + LOL', accent: '#ff5377', secondaryAccent: '#809fff', numeral: '05',
    description: 'Series-native Valorant, CS2 and League of Legends intelligence joined by one roster, map and matchup lab.',
    leagues: ['Valorant', 'Counter-Strike 2', 'League of Legends'],
  },
]

export const sportById = id => sports.find(sport => sport.id === id) || sports[0]

const researchNav = sport => [
  ['Overview', sport.route],
  ['Leagues', `${sport.route}/leagues`],
  ['Games', `${sport.route}/games`],
  ['Teams', `${sport.route}/teams`],
  ['Players', `${sport.route}/players`],
  ['Builder', `${sport.route}/builder`],
  ['Models', `${sport.route}/models`],
  ['Data', `${sport.route}/data`],
]

export const sportNavigation = {
  baseball: [
    ['Overview', '/baseball'], ['Games', '/schedule'], ['Standings', '/standings'], ['Teams', '/teams'], ['Players', '/players'],
    ['Live', '/live'], ['Builder', '/builder'], ['Player props', '/props-builder'], ['Models', '/model'],
    ['Guarantees', '/baseball/guarantees'], ['Alter ego', '/alter-ego'],
  ],
  'american-football': sport => [
    ['Overview', sport.route], ['Games', `${sport.route}/games`], ['Teams', `${sport.route}/teams`],
    ['Players', `${sport.route}/players`], ['NFL Builder', `${sport.route}/builder`],
    ['Models', `${sport.route}/models`], ['Data', `${sport.route}/data`],
  ],
  default: researchNav,
}
