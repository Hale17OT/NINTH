import { dataService as data } from "../services/dataService.js";

export const apiController = {
  dashboard: async (req, res) => res.json(await data.dashboard()),
  model: async (req, res) => res.json(await data.model()),
  modelResults: async (req, res) =>
    res.json(
      await data.modelResults(
        req.query.date,
        Number(req.query.page) || 1,
        Number(req.query.page_size) || 10,
        req.query.market || "moneyline",
        Object.prototype.hasOwnProperty.call(req.query, "prop_types")
          ? String(req.query.prop_types).split(",").filter(Boolean)
          : undefined,
      ),
    ),
  projectionBoard: async (req, res) =>
    res.json(
      await data.projectionBoard(
        req.query.start_date,
        Number(req.query.days) || 7,
      ),
    ),
  playerProps: async (req, res) =>
    res.json(
      await data.playerProps(
        req.query.start_date,
        Number(req.query.days) || 1,
        ["1", "true", "yes"].includes(String(req.query.refresh || "").toLowerCase()),
      ),
    ),
  games: async (req, res) =>
    res.json(await data.games(req.path.split("/").pop(), req.query.date)),
  game: async (req, res) => res.json(await data.game(req.params.id)),
  gameSummary: async (req, res) =>
    res.json(await data.gameSummary(req.params.id)),
  live: async (req, res) => res.json(await data.live(req.params.id)),
  teams: async (req, res) => res.json(await data.teams()),
  team: async (req, res) => res.json(await data.team(req.params.id)),
  players: async (req, res) => res.json(await data.players()),
  player: async (req, res) => res.json(await data.player(req.params.id)),
  betting: async (req, res) => res.json(await data.betting()),
  trends: async (req, res) => res.json(await data.trends()),
  rankings: async (req, res) => res.json(await data.rankings()),
  injuries: (req, res) => res.json(data.injuries()),
  search: async (req, res) => res.json(await data.search(req.query.q || "")),
  health: async (req, res) => res.json(await data.health()),
  slips: async (req, res) => res.json(await data.slips()),
  importSlip: async (req, res) =>
    res.status(201).json(await data.importSlip(req.body)),
};
