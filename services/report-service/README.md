# Report Generation Service

A light python api to generate reports. Does what the jupyter notebook does.

## Build

```
docker buildx build -t <username>/report-service .
docker push <username>/report-service:latest
```

## Run

edit the docker compose to use your <username>

```
docker-compose up -d
```
