export const workspaceData = {
  football: {
    unit: 'match', subject: 'club', person: 'player',
    competitions: ['Premier League', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1', 'UEFA Champions League', 'UEFA Europa League', 'UEFA Conference League', 'FA Cup', 'EFL Cup', 'Copa del Rey', 'DFB-Pokal', 'Coppa Italia', 'Coupe de France'],
    leagues: ['Competition identity', 'Domestic / European scope', 'Country and season', 'Data coverage'],
    games: ['Fixture and kickoff', 'Projected score matrix', '1X2 / totals / BTTS', 'Lineup availability'],
    teams: ['Attack and defence strength', 'xG and xGA form', 'Set-piece profile', 'Squad availability'],
    players: ['Expected minutes', 'xG+xA contribution', 'On-ball progression', 'Role and availability'],
    feed: 'Football-Data.co.uk + FPL + StatsBomb Open Data',
  },
  'american-football': {
    unit: 'game', subject: 'team', person: 'player', competitions: ['NFL'],
    leagues: ['League identity', 'Conference structure', 'Season phase', 'Data coverage'],
    games: ['Kickoff and weather', 'Joint score distribution', 'Spread / total / moneyline', 'Injury uncertainty'],
    teams: ['Opponent-adjusted EPA', 'Success and explosive rates', 'Drive efficiency', 'Line continuity'],
    players: ['Quarterback value', 'Usage and participation', 'Separation / pressure', 'Availability'],
    feed: 'nflverse open schedules, rosters and play-by-play',
  },
  basketball: {
    unit: 'game', subject: 'team', person: 'player', competitions: ['NBA'],
    leagues: ['League identity', 'Conference structure', 'Season phase', 'Data coverage'],
    games: ['Tipoff and rest', 'Pace distribution', 'Spread / total / moneyline', 'Lineup scenarios'],
    teams: ['Possession efficiency', 'Shot-quality profile', 'Transition and half court', 'Rotation stability'],
    players: ['RAPM impact', 'Minutes distribution', 'Usage and efficiency', 'Availability'],
    feed: 'Open NBA Stats mirror + official endpoints',
  },
  esports: {
    unit: 'series', subject: 'team', person: 'player', competitions: ['Valorant', 'Counter-Strike 2', 'League of Legends'],
    leagues: ['Discipline identity', 'Circuit and tournament', 'Region and tier', 'Data coverage'],
    games: ['Series and event tier', 'Conditional map tree', 'Match / map markets', 'Pick-ban state'],
    teams: ['Map pool strength', 'Opponent-adjusted form', 'Roster continuity', 'LAN and region context'],
    players: ['Map-adjusted impact', 'Opening-duel value', 'Role stability', 'Roster availability'],
    feed: 'Liquipedia MediaWiki API + CS API statistical supplement',
  },
}

export const esportsDisciplines = [
  {
    id: 'valorant', name: 'Valorant', code: 'VAL', accent: '#ff5377',
    leagues: 'VCT International + Challengers',
    engine: 'Patch-aware map ratings, agent-role strength, side splits and veto simulation.',
    source: 'Liquipedia MediaWiki API',
  },
  {
    id: 'cs2', name: 'Counter-Strike 2', code: 'CS2', accent: '#809fff',
    leagues: 'Tier-one + tier-two circuits',
    engine: 'Map pools, economy conversion, opening duels, LAN context and veto simulation.',
    source: 'Liquipedia MediaWiki API / CS API',
  },
  {
    id: 'lol', name: 'League of Legends', code: 'LOL', accent: '#d7ae45',
    leagues: 'LCK + LPL + LEC + LCS + international events',
    engine: 'Patch-aware team ratings, side strength, roster continuity, objective control and series simulation.',
    source: 'Liquipedia MediaWiki API',
  },
]
