FROM python:3.12-slim AS build
WORKDIR /docs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdocs build --strict

FROM nginx:alpine
COPY nginx-gzip.conf /etc/nginx/conf.d/gzip.conf
COPY --from=build /docs/site /usr/share/nginx/html
