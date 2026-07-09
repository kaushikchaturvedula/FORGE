# Deploying FORGE to Alibaba Cloud ECS

The realtime bridge needs persistent WebSocket connections up to ~120 minutes, so
FORGE deploys to **ECS** (full control of proxy timeouts) rather than SAE/Function
Compute. This folder holds the runtime manifests.

> Note: these nginx + Compose manifests are the reproducible deploy path; the externally verified Jul 6, 2026 demo ran the same backend via **uvicorn behind Caddy** (automatic Let's Encrypt TLS) — see deploy/ALIBABA_CLOUD_PROOF.md.

## Prerequisites

- An Alibaba Cloud account with **OSS**, **ACR**, and **ECS** enabled.
- A **DashScope (Model Studio) API key** with access to a realtime omni model.
- An AccessKey pair (`ALIBABA_CLOUD_ACCESS_KEY_ID` / `_SECRET`).

## 1. OSS — static assets

```bash
# Create a bucket (example region ap-southeast-1 / Singapore, matching the intl endpoint)
ossutil mb oss://forge-assets --region ap-southeast-1
# Upload the submission-safe CC BY 3.0 CNC clip (CNCBUL, YouTube) + any large schematics
ossutil cp ./datasets/cnc2.mp4 oss://forge-assets/video/
```
At startup FORGE can pull these via `app.cloud.alibaba.download_object` (the `oss2` SDK).
`GET /cloud/health` then reports the bucket region — the deployment proof.

## 2. ACR — image

CI builds and pushes `forge:latest` + `forge:<sha>`. To build locally and push:

```bash
docker build -f backend/Dockerfile -t $ACR_REGISTRY/$ACR_NAMESPACE/forge:latest .
docker login $ACR_REGISTRY -u $ACR_USERNAME --password-stdin <<< "$ACR_PASSWORD"
docker push $ACR_REGISTRY/$ACR_NAMESPACE/forge:latest
```

## 3. ECS — host

```bash
# On the ECS instance (Ubuntu/Alibaba Cloud Linux):
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
sudo mkdir -p /opt/forge && cd /opt/forge
# copy deploy/ecs/docker-compose.yml and deploy/ecs/nginx.conf here, plus a .env:
cat > .env <<'ENV'
ACR_REGISTRY=...
ACR_NAMESPACE=...
TAG=latest
DASHSCOPE_API_KEY=...
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
OSS_BUCKET=forge-assets
OSS_ENDPOINT=https://oss-ap-southeast-1.aliyuncs.com
OSS_REGION=ap-southeast-1
FORGE_ALLOWED_ORIGINS=https://your-domain
ENV
docker login $ACR_REGISTRY -u $ACR_USERNAME --password-stdin <<< "$ACR_PASSWORD"
docker compose up -d
```

Open the **ECS security group** for ports 80/443 (and 22 for SSH). Put TLS in front
(Alibaba Cloud SLB/ALB or certbot on nginx). The `nginx.conf` here already sets the
long `proxy_read_timeout` required for 120-minute realtime sessions.

## 4. CI/CD secrets (GitHub → Settings → Secrets)

`ACR_REGISTRY`, `ACR_NAMESPACE`, `ACR_USERNAME`, `ACR_PASSWORD`,
`ECS_HOST`, `ECS_USER`, `ECS_SSH_KEY`,
plus the runtime secrets the host `.env` uses. On push to `main`, the workflow runs the
hermetic tests, builds, pushes to ACR, and rolls out on ECS over SSH.

## 5. Verify

```bash
curl https://your-domain/healthz
curl https://your-domain/cloud/health   # shows live OSS + DashScope regions
```
