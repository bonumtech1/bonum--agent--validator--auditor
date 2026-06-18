# Despliegue (AWS Lightsail, igual que `services--sessions`)

El pipeline es idéntico al de sesiones: **push → build Docker → ECR → Lightsail**.

- `push` a `develop` → `.github/workflows/dev.yml` → servicio Lightsail **dev**
- `push` a `main` → `.github/workflows/production.yml` → servicio Lightsail **prod**

Las variables de entorno del contenedor salen de `.env.dev` / `.env.prod`
(commiteados, **sin secretos**). El `MONGODB_URI` se inyecta desde GitHub Secrets.

## Prerequisitos (una sola vez, los crea DevOps)

### 1. Repositorios ECR
```
services-agents-development
services-agents-production
```

### 2. Servicios de contenedor Lightsail (puerto 8000)
```
container-agents-development
container-agents-production
```
```bash
aws lightsail create-container-service \
  --service-name container-agents-development \
  --power nano --scale 1 --region us-east-1
```

### 3. Secrets del repo en GitHub
| Secret | Para qué |
|---|---|
| `AWS_ACCESS_KEY_ID` | credenciales AWS (ECR + Lightsail) |
| `AWS_SECRET_ACCESS_KEY` | idem |
| `MONGODB_URI` | connection string de Mongo (se inyecta en runtime) |

## Después del primer deploy

1. Lightsail asigna una URL pública al servicio. Obtenla:
   ```bash
   aws lightsail get-container-services \
     --service-name container-agents-development \
     --query 'containerServices[0].url' --output text
   ```
2. Pon esa URL en `services--sessions/.env.dev` → `AGENT_API=<url>` y redeploy
   sesiones. **Recién ahí el validador empieza a actuar de verdad.**
3. Verifica:
   - `GET <url>/health` → `{"status":"ok","db":"connected"}`
   - `GET <url>/docs` → Swagger
   - `GET <url>/alerts/ui` → centro de alertas

## Notas importantes

- **1 solo worker / 1 sola instancia (`--scale 1`)**: el scheduler interno
  (APScheduler) debe correr una única vez. Con varias réplicas, el barrido horario
  se ejecutaría N veces. Si en el futuro se escala horizontalmente, hay que mover
  el scheduler a una instancia dedicada o usar un lock.
- **Healthcheck**: `path: /health`, `successCodes: 200-399`.
- **Mongo**: rotar la credencial expuesta y usar un usuario dedicado (no `god`).
- `.env.dev`/`.env.prod` NO deben contener secretos (van a git). Cualquier secreto
  nuevo → GitHub Secret + inyectarlo en el paso `Create containers.json`.
- Las URLs de prod en `.env.prod` están como placeholder — **verificar la de
  sesiones** (`SESSIONS_SERVICE_URL`) antes del primer deploy a main.
