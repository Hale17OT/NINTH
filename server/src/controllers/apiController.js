import { dataService as data } from "../services/dataService.js";
import { multiSportProvider } from "../services/multiSportProvider.js";

export const apiController = {
  dashboard: async (req, res) => {
    const dashboard = await data.dashboard();
    res
      .set("Cache-Control", "public, s-maxage=300, stale-while-revalidate=60")
      .json(dashboard);
  },
  scoreboard: async (req, res) => {
    const scoreboard = await data.scoreboard(req.query.date);
    res
      .set("Cache-Control", "public, s-maxage=45, stale-while-revalidate=120")
      .json(scoreboard);
  },
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
  playerPropGuarantees: async (req, res) =>
    res.json(
      await data.playerPropGuarantees(
        Number(req.query.minimum_samples) || 1,
        req.query.search || "",
        Object.prototype.hasOwnProperty.call(req.query, "prop_types")
          ? String(req.query.prop_types).split(",").filter(Boolean)
          : undefined,
      ),
    ),
  recordPlayerPropBuild: async (req, res) =>
    res.status(201).json(await data.recordPlayerPropBuild(req.body)),
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
  multiSportDirectory: async (req, res) => res.json(await multiSportProvider.directory(
    req.params.sport,
    req.params.type,
    { ...req.query },
  )),
  multiSportWorkspace: async (req, res) => res.json(await multiSportProvider.workspace(
    req.params.sport,
    req.params.scope,
    req.params.id,
    { ...req.query },
  )),
  slips: async (req, res) => res.json(await data.slips(req.auth.user.id)),
  importSlip: async (req, res) =>
    res.status(201).json(await data.importSlip(req.auth.user.id, req.body)),
  alterEgo: async (req, res) => res.json(await data.alterEgo(req.auth.user.id)),
  importMelbetHistory: async (req, res) =>
    res.status(201).json(await data.importMelbetHistory(req.auth.user.id, req.body)),
  importMelbetHistoryBatch: async (req, res) =>
    res.status(201).json(await data.importMelbetHistoryBatch(req.auth.user.id, req.body)),
};
