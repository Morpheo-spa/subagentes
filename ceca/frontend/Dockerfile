# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# DEVELOPMENT ONLY: the Vite dev server, source maps and all. Built by
# docker-compose.dev.yml; docker-compose.yml builds `runtime` below.
FROM deps AS dev
LABEL com.estampa.target="dev" com.estampa.deployable="false"
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM deps AS build
COPY . .
RUN npm run build

FROM nginx:alpine AS runtime
LABEL com.estampa.target="runtime" com.estampa.deployable="true"
COPY --from=build /app/dist /usr/share/nginx/html
# The SPA owns its routes; nginx must not 404 on a deep link.
# server_tokens off: the version banner is free reconnaissance. The rest of the
# security headers come from the `security-headers` Traefik middleware.
RUN printf 'server {\n\
  listen 80;\n\
  server_tokens off;\n\
  root /usr/share/nginx/html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
