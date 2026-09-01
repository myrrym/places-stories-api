# Deploying

Two paths: what v1 actually runs on, and what it grows into. Both are here
because picking the cheap one deliberately is engineering, and picking it
silently is not.

## v1: one EC2 instance, the same compose file

The stack is three containers. A single small instance runs them for about
**US$12/month**, and the deploy is the same `docker compose up` that runs
locally — no drift between what you develop against and what serves traffic.

**Instance:** `t4g.small` (ARM, 2 GB), Amazon Linux 2023, 20 GB gp3.
**Security group:** inbound 80 and 443 from anywhere, 22 from your IP only.
Postgres and Redis stay on the Docker network and are never published.

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user   # log out and back in

git clone https://github.com/myrrym/places-stories-api.git
cd places-stories-api
cp .env.example .env
```

Edit `.env` before the first run:

```bash
POSTGRES_PASSWORD=<something long and random>
DATABASE_URL=postgresql+asyncpg://places:<same password>@db:5432/places
TRUSTED_PROXY_CIDRS=["172.16.0.0/12"]   # so the reverse proxy's XFF is believed
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_PER_DAY=1000
```

Then:

```bash
docker compose up -d --build
curl localhost:8000/health
```

### TLS

Put Caddy in front — it obtains and renews a Let's Encrypt certificate on its
own. Add to `docker-compose.yml`:

```yaml
  proxy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on: [api]
```

`Caddyfile`:

```
api.example.com {
    reverse_proxy api:8000
}
```

Point an A record at the instance's Elastic IP and Caddy handles the rest.
Remove the `ports:` block from the `api` service so it is only reachable through
the proxy.

### Backups

The whole dataset is in git. `data/places/*.yaml` is the source of truth and the
database is a projection of it — a rebuild is `alembic upgrade head` then
`python -m ingestion.load`. Snapshot the EBS volume anyway for the cache and
runtime state, but the recovery story does not depend on it.

### Updating

```bash
git pull && docker compose up -d --build
```

The API container runs `alembic upgrade head` and the loader on start, so a
deploy that includes new places or a schema change needs no extra step.

## Production: ECS Fargate + RDS + ElastiCache

The managed architecture this grows into:

```
Route 53 ─▶ ALB (TLS via ACM) ─▶ ECS Fargate service (2+ tasks)
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
              RDS PostgreSQL 16              ElastiCache Redis
              (PostGIS extension)            (single node → replica group)
                        ▲
                        │ batch
                 ECS scheduled task: python -m ingestion.load
```

- **Image:** built by CI, pushed to ECR, deployed by tag.
- **Secrets:** `DATABASE_URL` and `REDIS_URL` from Secrets Manager, injected as
  task-definition secrets. Never in the image, never in `.env` on a host.
- **Networking:** tasks in private subnets, ALB public. RDS and ElastiCache
  reachable only from the task security group.
- **Migrations:** a one-off ECS task running `alembic upgrade head` before the
  service update, not on container start — with more than one task, start-time
  migration is a race.
- **Ingestion:** an EventBridge-scheduled ECS task. It is already a batch job
  with no shared state, so it lifts across unchanged.
- **Scaling:** the API is stateless; scale on ALB request count. PostGIS is the
  first thing to feel pressure — a read replica is the next step, and the
  `/v1/stats` hit rate tells you whether the cache is doing its job before you
  pay for one.
- **Observability:** CloudWatch for logs and ALB metrics; `/v1/stats` for cache
  behaviour; `/health` as the ALB target-group health check.

### Why v1 is not on this

Roughly **US$50–70/month** for Fargate + RDS + ElastiCache at their smallest
sizes, to serve 57 places. That is not a technical constraint, it is arithmetic.
The architecture above is the answer when there is traffic to justify it; the
single instance is the answer today, and the compose file is identical either
way.

## Free-tier note

An `t4g.small` is not always free-tier eligible, and the free tier expires. If
this is running on a personal account, set a billing alarm before the first
`docker compose up`, not after the first invoice.
