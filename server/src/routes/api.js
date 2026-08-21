import { Router } from "express";
import { apiController as c } from "../controllers/apiController.js";
import { requireAuth } from "../middleware/authenticate.js";
import { requireCsrf } from "../middleware/csrf.js";
import { signModelArtifact } from "../services/modelArtifactSigner.js";

const r = Router();
const wrap = (fn) => (req, res, next) =>
  Promise.resolve(fn(req, res, next)).catch(next);

r.get("/health", wrap(c.health));
r.get("/internal/model-artifacts/sign", wrap(signModelArtifact));
r.get("/multisport/:sport/workspace/:scope/:id", wrap(c.multiSportWorkspace));
r.get("/multisport/:sport/:type", wrap(c.multiSportDirectory));
r.get("/model/results", wrap(c.modelResults));
r.get("/model", wrap(c.model));
r.get("/projection-board", wrap(c.projectionBoard));
r.get("/player-props", wrap(c.playerProps));
r.get("/player-props/guarantees", wrap(c.playerPropGuarantees));
r.post("/player-props/build-snapshots", requireCsrf, ...requireAuth, wrap(c.recordPlayerPropBuild));
r.get("/slips", ...requireAuth, wrap(c.slips));
r.post("/slips/import", requireCsrf, ...requireAuth, wrap(c.importSlip));
r.get("/alter-ego", ...requireAuth, wrap(c.alterEgo));
r.post("/alter-ego/import", requireCsrf, ...requireAuth, wrap(c.importMelbetHistory));
r.post("/alter-ego/import-batch", requireCsrf, ...requireAuth, wrap(c.importMelbetHistoryBatch));
r.get("/dashboard", wrap(c.dashboard));
r.get("/games/live", wrap(c.games));
r.get("/games/today", wrap(c.games));
r.get("/games/completed", wrap(c.games));
r.get("/games/:id/live", wrap(c.live));
r.get("/games/:id/summary", wrap(c.gameSummary));
r.get("/games/:id", wrap(c.game));
r.get("/teams", wrap(c.teams));
r.get("/teams/:id", wrap(c.team));
r.get("/players", wrap(c.players));
r.get("/players/:id", wrap(c.player));
r.get("/trends", wrap(c.trends));
r.get("/rankings", wrap(c.rankings));
r.get("/injuries", c.injuries);
r.get("/search", wrap(c.search));

export default r;
