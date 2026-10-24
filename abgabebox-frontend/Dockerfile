FROM node:25-bookworm@sha256:78839ac448c23517f8eab2e8f7943d9b4f73979eb7f8bed2c73dbf72ff869e7b AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

FROM node:25-bookworm@sha256:78839ac448c23517f8eab2e8f7943d9b4f73979eb7f8bed2c73dbf72ff869e7b AS build

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
RUN mkdir -p public
COPY . .
RUN npm run build

FROM node:25-bookworm-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS run

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
