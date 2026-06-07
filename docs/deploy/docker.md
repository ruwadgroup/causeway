# Deploying to Docker

Via the `causeway[docker]` adapter.

## Install

```bash
uv add "causeway[docker]"
```

## Register

```python
# src/app/plugins.py
from causeway import register
from causeway.contrib.docker import DockerDeploy

register(DockerDeploy(
    image="my-registry/my-app",
    base_image="python:3.12-slim",
))
```

## Deploy

```bash
causeway build
causeway deploy docker
```

What that does:

1. Reads the registered `DockerDeploy` adapter.
2. Generates a `Dockerfile` from a minimal template (entry: `uvicorn app:app --host 0.0.0.0 --port 8000`).
3. Calls `docker build -t <image> .`.
4. Optionally `docker push <image>` if `push=True` in the adapter config.

## Custom Dockerfile

If you'd rather write your own, skip the plugin and:

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY src ./src
COPY causeway.toml ./

ENV CAUSEWAY_ENV=prod
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Running locally

```bash
docker run -p 8000:8000 -e DATABASE_URL=... my-registry/my-app
```

## See also

- [Deploying overview](./index.md)
- [`causeway deploy`](../reference/cli/deploy.md)
- [`DeployTarget` contract](../reference/classes/contracts.md#deploytarget)
