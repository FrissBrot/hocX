FROM node:22-bookworm@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8 AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-bookworm@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8 AS build

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
RUN mkdir -p public
COPY . .
RUN npm run build

FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS run

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
