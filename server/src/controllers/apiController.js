import { dataService as data } from '../services/dataService.js'

export const apiController = {
  dashboard: async (req, res) => res.json(await data.dashboard()),
  model: async (req, res) => res.json(await data.model()),
  projectionBoard: async (req, res) => res.json(await data.projectionBoard(req.query.start_date, Number(req.query.days) || 7)),
  games: async (req, res) => res.json(await data.games(req.path.split('/').pop(), req.query.date)),
  game: async (req, res) => res.json(await data.game(req.params.id)),
  gameSummary: async (req, res) => res.json(await data.gameSummary(req.params.id)),
  live: async (req, res) => res.json(await data.live(req.params.id)),
  teams: async (req, res) => res.json(await data.teams()),
  team: async (req, res) => res.json(await data.team(req.params.id)),
  players: async (req, res) => res.json(await data.players()),
  player: async (req, res) => res.json(await data.player(req.params.id)),
  betting: async (req, res) => res.json(await data.betting()),
  trends: async (req, res) => res.json(await data.trends()),
  rankings: async (req, res) => res.json(await data.rankings()),
  injuries: (req, res) => res.json(data.injuries()),
  search: async (req, res) => res.json(await data.search(req.query.q || '')),
  health: async (req, res) => res.json(await data.health()),
  slips: async (req, res) => res.json(await data.slips()),
  importSlip: async (req, res) => res.status(201).json(await data.importSlip(req.body)),
}
