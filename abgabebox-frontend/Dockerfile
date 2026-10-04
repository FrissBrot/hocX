FROM node:22-bookworm AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-bookworm AS build

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
RUN mkdir -p public
COPY . .
RUN npm run build

FROM node:22-bookworm-slim AS run

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# next-intl Namespace-Kataloge (i18n/request.ts liest sie zur Laufzeit per fs von <cwd>/messages) -
# wie public/ und .next/static oben nicht Teil des Standalone-Traces, muss von Hand kopiert werden.
COPY --from=build --chown=node:node /app/messages ./messages

USER node

EXPOSE 3000

CMD ["node", "server.js"]
