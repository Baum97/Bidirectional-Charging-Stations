FROM node:20-alpine AS base

ENV NODE_ENV=production \
    PORT=8080 \
    WS_PATH=/ws

WORKDIR /app

# Copy manifest files (supports lockfile when present)
COPY package*.json ./
# Use npm install instead of npm ci since no lockfile is committed yet
RUN npm install --omit=dev --no-audit --no-fund

COPY server.js ./
COPY public ./public

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD node -e "fetch('http://127.0.0.1:'+process.env.PORT+'/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
