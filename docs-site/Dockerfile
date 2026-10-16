FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build
WORKDIR /docs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdocs build --strict

FROM nginxinc/nginx-unprivileged:alpine@sha256:378d0c32f6562f7fd9629170797f57d2b953aa09be983b3daaf4809bb039ca00
USER root
RUN sed -i 's/8080/80/g' /etc/nginx/conf.d/default.conf
COPY nginx-gzip.conf /etc/nginx/conf.d/gzip.conf
COPY --from=build /docs/site /usr/share/nginx/html
USER 101
