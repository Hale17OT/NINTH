import { savedService } from './saved.service.js'

export const savedController = {
  list: async (req, res) => res.json(await savedService.list(req.params.type, req.auth.user.id)),
  get: async (req, res) => res.json(await savedService.get(req.params.type, req.auth.user.id, req.params.id)),
  create: async (req, res) => res.status(201).json(await savedService.create(req.params.type, req.auth.user.id, req.validated)),
  remove: async (req, res) => res.json(await savedService.remove(req.params.type, req.auth.user.id, req.params.id)),
}
