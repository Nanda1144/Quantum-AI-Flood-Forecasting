# deployment

Build, containerisation, and deployment manifests for Q-FLARE.

> **Status:** placeholder.

## Notes

Each service runs standalone today:

- `ai-service` — Node/Express on port 3000.
- `frontend` — static build (Vite) proxying `/api` to `ai-service`.

Future: Docker Compose / Kubernetes manifests to run all microservices with the
shared edge `backend` gateway and load balancing.