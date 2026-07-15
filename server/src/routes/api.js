import { Router } from 'express'
import { apiController as c } from '../controllers/apiController.js'

const r = Router()
const wrap = fn => (req,res,next) => Promise.resolve(fn(req,res,next)).catch(next)

r.get('/health',wrap(c.health))
r.get('/model',wrap(c.model))
r.get('/projection-board',wrap(c.projectionBoard))
r.get('/slips',wrap(c.slips)); r.post('/slips/import',wrap(c.importSlip))
r.get('/dashboard',wrap(c.dashboard))
r.get('/games/live',wrap(c.games)); r.get('/games/today',wrap(c.games)); r.get('/games/completed',wrap(c.games))
r.get('/games/:id/live',wrap(c.live)); r.get('/games/:id/summary',wrap(c.gameSummary)); r.get('/games/:id',wrap(c.game))
r.get('/teams',wrap(c.teams)); r.get('/teams/:id',wrap(c.team))
r.get('/players',wrap(c.players)); r.get('/players/:id',wrap(c.player))
r.get('/trends',wrap(c.trends)); r.get('/rankings',wrap(c.rankings)); r.get('/injuries',c.injuries)
r.get('/search',wrap(c.search))

export default r
