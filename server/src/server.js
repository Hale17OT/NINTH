import 'dotenv/config';import app from'./app.js';const port=process.env.PORT||3001;app.listen(port,()=>console.log(`Diamond Intel API listening on ${port}`))
