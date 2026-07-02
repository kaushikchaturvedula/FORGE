# Alibaba Cloud Deployment Proof

FORGE runs end-to-end on Alibaba Cloud. This document is the single place a judge can
verify that — the live URL, the recording, and the exact code that calls Alibaba Cloud
services.

> Fill the bracketed values in once deployed. The code references are already real.

## 1. Live service

- **App URL (ECS + nginx):** `https://[YOUR_ECS_DOMAIN_OR_IP]`
- **Health:** `https://[YOUR_ECS_DOMAIN_OR_IP]/healthz`
- **Cloud proof endpoint:** `https://[YOUR_ECS_DOMAIN_OR_IP]/cloud/health`
- **Deployment recording:** `[LINK_TO_SCREEN_RECORDING]`

`GET /cloud/health` returns the live OSS bucket region and the DashScope region the
realtime model is served from — proving both Alibaba Cloud services are in use:

```json
{
  "provider": "Alibaba Cloud",
  "oss": { "configured": true, "bucket": "forge-assets", "region": "oss-ap-southeast-1", "reachable": true },
  "dashscope": { "configured": true, "region": "ap-southeast-1 (Singapore)",
                 "endpoint": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime",
                 "model": "qwen3.5-omni-plus-realtime" }
}
```

## 2. Which Alibaba Cloud services and where in the code

| Service | What it does for FORGE | Code |
|---|---|---|
| **Model Studio / DashScope** (Qwen-Omni-Realtime) | The entire AI core — audio in/out, function calling, vision — over one realtime WebSocket | [backend/app/realtime/session.py](../backend/app/realtime/session.py), endpoint built in [backend/app/config.py](../backend/app/config.py) |
| **OSS** (Object Storage, via `oss2`) | Stores + serves the large static assets (CNC video, schematics) fetched at startup | [backend/app/cloud/alibaba.py](../backend/app/cloud/alibaba.py) — `read_object` / `download_object` / `oss_status` |
| **ACR** (Container Registry) | Hosts the built Docker image | [backend/Dockerfile](../backend/Dockerfile), pushed by [.github/workflows/deploy.yml](../.github/workflows/deploy.yml) |
| **ECS** (Elastic Compute Service) | Hosts the FastAPI backend with persistent (≤120 min) WebSocket sessions | [deploy/ecs/](./ecs/) — compose + nginx (long-lived WS timeouts) |

**Why ECS, not SAE or Function Compute:** the realtime bridge holds a WebSocket open
for up to ~120 minutes. Function Compute force-terminates long connections; SAE's
long-WebSocket behaviour behind its load balancer is not clearly documented (the ALB
default idle timeout is 60 s). ECS gives full control of the proxy timeouts — see
[deploy/ecs/nginx.conf](./ecs/nginx.conf) (`proxy_read_timeout 7800s`).

## 3. Reproduce the deploy

1. **OSS:** create bucket `forge-assets` (region e.g. `ap-southeast-1`); upload the
   CC BY 3.0 CNC clip (CNCBUL, YouTube) + schematics. (See [deploy/ecs/README.md](./ecs/README.md).)
2. **ACR:** create a namespace; CI pushes `forge:latest` + `forge:<sha>`.
3. **ECS:** provision an instance, install Docker + Compose, place
   `deploy/ecs/docker-compose.yml` + `nginx.conf` in `/opt/forge`, set the `.env`,
   `docker login` to ACR, `docker compose up -d`.
4. **CI/CD:** set the repo secrets listed in [ecs/README.md](./ecs/README.md);
   pushes to `main` then build → push to ACR → SSH roll-out on ECS automatically.

## 4. Secrets (repo + ECS `.env`)

`DASHSCOPE_API_KEY`, `ALIBABA_CLOUD_ACCESS_KEY_ID`, `ALIBABA_CLOUD_ACCESS_KEY_SECRET`,
`OSS_BUCKET`, `OSS_ENDPOINT`, `OSS_REGION`, and for CI: `ACR_REGISTRY`, `ACR_NAMESPACE`,
`ACR_USERNAME`, `ACR_PASSWORD`, `ECS_HOST`, `ECS_USER`, `ECS_SSH_KEY`. None are committed.
