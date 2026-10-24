FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
WORKDIR /docs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdocs build --strict

FROM nginxinc/nginx-unprivileged:alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e
USER root
RUN sed -i 's/8080/80/g' /etc/nginx/conf.d/default.conf
COPY nginx-gzip.conf /etc/nginx/conf.d/gzip.conf
COPY --from=build /docs/site /usr/share/nginx/html
USER 101
