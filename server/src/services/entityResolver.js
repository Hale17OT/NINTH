const normalize = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
  .toLowerCase().replace(/\b(fc|cf|afc|the)\b/g, '').replace(/[^a-z0-9]+/g, ' ').trim()

const aliases = new Map(Object.entries({
  'man utd': 'manchester united', 'man united': 'manchester united',
  'man city': 'manchester city', 'spurs': 'tottenham hotspur',
  'wolves': 'wolverhampton wanderers', 'inter': 'internazionale',
  'psg': 'paris saint germain', 'la rams': 'los angeles rams',
  'washington football team': 'washington commanders',
}))

export const normalizedEntityName = value => aliases.get(normalize(value)) || normalize(value)

export class EntityResolver {
  constructor(entities = []) { this.replace(entities) }
  replace(entities) {
    this.entities = [...entities]
    this.byId = new Map(this.entities.map(row => [String(row.id), row]))
    this.byName = new Map()
    for (const entity of this.entities) {
      for (const value of [entity.name, entity.shortName, entity.code, ...(entity.aliases || [])]) {
        const key = normalizedEntityName(value)
        if (!key) continue
        const current = this.byName.get(key) || []
        current.push(entity); this.byName.set(key, current)
      }
    }
  }
  resolve(value, context = {}) {
    if (value == null) return { entity: null, state: 'unmatched' }
    const byId = this.byId.get(String(value))
    if (byId) return { entity: byId, state: 'exact-id' }
    let matches = this.byName.get(normalizedEntityName(value)) || []
    if (context.competitionId) matches = matches.filter(row => String(row.competitionId) === String(context.competitionId))
    if (matches.length === 1) return { entity: matches[0], state: 'exact-name' }
    return { entity: null, state: matches.length ? 'ambiguous' : 'unmatched', candidates: matches }
  }
}
