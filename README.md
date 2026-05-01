# Order Service

The Order Service manages customer orders. It calls the Catalog Service over HTTP to check product information and reserve stock before saving an order.

## Responsibilities

- Create orders.
- List orders.
- Read order details.
- Collaborate with Catalog Service.

## Run Locally

```powershell
cd D:\Mtech\Sem3\Scalable\Assignment\order-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:CATALOG_SERVICE_URL="http://localhost:8001"
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

## Run Tests

```powershell
cd D:\Mtech\Sem3\Scalable\Assignment\order-service
pytest
```

## Pre-commit

This repository has its own pre-commit configuration in `.pre-commit-config.yaml`.

```powershell
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/orders` | Create order |
| GET | `/orders` | List orders |
| GET | `/orders/{order_id}` | Get order |

## Docker

Build the image:

```powershell
docker build -t order-service:1.0 .
```

Run the container. The Catalog Service must be reachable through `CATALOG_SERVICE_URL`.

```powershell
docker network create store-network
docker run -d --name order-service --network store-network -p 8002:8000 -e CATALOG_SERVICE_URL=http://catalog-service:8000 order-service:1.0
```

## Kubernetes

This repository owns its own Kubernetes manifests in the `k8s` folder.

The Catalog Service should be deployed first because this service calls it using the Kubernetes service name `catalog-service`.

For Minikube:

```powershell
minikube start
minikube docker-env | Invoke-Expression
docker build -t order-service:1.0 .
kubectl apply -f .\k8s\namespace.yaml
kubectl apply -f .\k8s\deployment.yaml
kubectl get all -n store-app
```

Access the service:

```powershell
minikube service order-service -n store-app
```

## GitHub Actions

This repository has its own workflow:

```text
.github/workflows/ci.yml
```

The workflow runs pre-commit checks, runs tests, and builds the Docker image.

The current workflow does not need credentials because it does not push images or deploy to a cloud cluster. If Docker image push is added later, add these secrets in GitHub repository `Settings` -> `Secrets and variables` -> `Actions`:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

If Kubernetes deployment is added later, add Kubernetes or cloud credentials as GitHub Actions secrets. Never hardcode passwords, tokens, or kubeconfig values in the workflow file.
