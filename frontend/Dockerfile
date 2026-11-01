FROM node:26-bookworm@sha256:fa52d1669505e29b58c042875b1d65c229e0787a3610fd52869b22b68e480853 AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

FROM node:26-bookworm@sha256:fa52d1669505e29b58c042875b1d65c229e0787a3610fd52869b22b68e480853 AS build

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
RUN mkdir -p public
COPY . .
RUN npm run build

FROM node:26-bookworm-slim@sha256:bc0a2afd3b74ce12222fc8bab99271e66257f021078f5f4a5d687a77d280c1d9 AS run

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# next-intl Namespace-Kataloge (frontend/i18n/request.ts liest sie zur Laufzeit per fs von
# <cwd>/messages) - wie public/ und .next/static oben nicht Teil des von "next build" erzeugten
# Standalone-Traces (das verfolgt nur statisch importierte/require()te Dateien), muss also
# ebenfalls von Hand kopiert werden.
COPY --from=build --chown=node:node /app/messages ./messages

USER node

EXPOSE 3000

CMD ["node", "server.js"]
