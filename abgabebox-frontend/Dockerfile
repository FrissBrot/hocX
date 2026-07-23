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

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
