import 'dotenv/config'
import app from './app.js'
import { startReadinessScheduler } from './services/readinessScheduler.js'
import { assertProductionAuthConfig } from './config/auth.js'

const port = process.env.PORT || 3001
assertProductionAuthConfig()
app.listen(port, () => {
  console.log(`NINTH API listening on ${port}`)
  startReadinessScheduler()
})
