# Servidor de Vacantes — Cooperativa San Pedro

Servidor (Flask + Docker) donde Talento Humano publica las vacantes que muestra
`https://sanpedroesmicoope.com.gt/pages/empleo.html`.

En producción, el mismo servidor local sirve también la página pública
(repositorio de la página, carpeta `Paginaweb-main`) a través de Caddy.

| Dirección | Uso |
|---|---|
| `https://sanpedroesmicoope.com.gt` | Página pública (archivos de `Paginaweb-main`) |
| `https://vacantes.sanpedroesmicoope.com.gt/talento-humano` | Talento Humano crea, edita, publica y oculta vacantes |
| `https://vacantes.sanpedroesmicoope.com.gt/admin` | Administración de usuarios (solo administradores) |
| `https://vacantes.sanpedroesmicoope.com.gt/api/listar` | Vacantes publicadas (la consume `empleo.html`) |


## Requisitos

- Servidor Linux (Ubuntu recomendado), siempre encendido, con Docker y Docker Compose.
- Registros DNS tipo **A** hacia la IP pública del servidor:
  `sanpedroesmicoope.com.gt`, `www.sanpedroesmicoope.com.gt` y `vacantes.sanpedroesmicoope.com.gt`.
  **No modificar los registros MX ni los del correo.**
  Cambiar el dominio principal solo cuando el servidor ya responda (ver paso 5), para evitar caídas.
- Puertos **80 y 443 TCP** abiertos desde internet hacia el servidor.
  - 443: HTTPS.
  - 80: validación y renovación automática del certificado (Let's Encrypt, vía Caddy).
  - El puerto interno 5001 **no** se expone.

## Instalación

La imagen se construye en el servidor con el `Dockerfile` de este repositorio.

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sudo sh

# 2. Código (los dos repositorios)
git clone <URL_REPO_PAGINA_WEB> /opt/Cotizador              # contiene Paginaweb-main
git clone <URL_REPO_SERVIDOR_VACANTES> /opt/servidor-vacantes
cd /opt/servidor-vacantes/produccion

# 3. Configuración
cp .env.example .env
nano .env        # ADMIN_CLAVE, SECRET_KEY (openssl rand -hex 32) y RUTA_PAGINA

# 4. Construir y arrancar
docker compose up -d --build
docker compose ps    # sanpedro-web y sanpedro-caddy en "Up"
```

A los 1–2 minutos (emisión del certificado) debe abrir
`https://vacantes.sanpedroesmicoope.com.gt/talento-humano`.
Primer acceso: usuario `ADMIN_USUARIO` / clave `ADMIN_CLAVE` del `.env`.

**Paso 5 — cambio del dominio principal.** Con `vacantes.` funcionando, apuntar
`sanpedroesmicoope.com.gt` y `www` a este servidor (hoy apuntan a GoDaddy). Caddy
obtiene el certificado automáticamente al llegar la primera visita.

## Variables del `.env`

| Variable | Descripción |
|---|---|
| `ADMIN_USUARIO`, `ADMIN_CLAVE` | Primer administrador. Solo se usan la primera vez; luego los usuarios se gestionan en `/admin`. |
| `SECRET_KEY` | Cadena aleatoria para firmar sesiones. Si cambia, se cierran las sesiones abiertas. |
| `SITIOS_PERMITIDOS` | Dominios que pueden leer las vacantes publicadas: `https://sanpedroesmicoope.com.gt,https://www.sanpedroesmicoope.com.gt` |
| `SESSION_COOKIE_SECURE` | `1` en producción (HTTPS). |
| `RUTA_PAGINA` | Ruta de la carpeta `Paginaweb-main` del repositorio de la página (ej. `/opt/Cotizador/Paginaweb-main`). |

## Datos y respaldos

Usuarios, vacantes e imágenes se guardan en el volumen Docker `produccion_datos_vacantes`
(JSON + archivos). Actualizar o reiniciar los contenedores no los borra.
**No usar `docker compose down -v`**: elimina el volumen.

Respaldo:

```bash
docker run --rm -v produccion_datos_vacantes:/datos -v "$PWD":/respaldo alpine \
  tar czf /respaldo/vacantes-$(date +%F).tar.gz -C /datos .
```

## Actualizar la página pública

```bash
cd /opt/Cotizador
git pull          # los cambios se ven al instante, sin reiniciar
```

## Actualizar el servidor de vacantes

```bash
cd /opt/servidor-vacantes
git pull
cd produccion
docker compose up -d --build
```

## Problemas comunes

| Síntoma | Revisar |
|---|---|
| El subdominio no abre / error de certificado | `docker compose logs caddy`. Suele ser DNS aún sin propagar o puertos 80/443 cerrados. |
| `empleo.html` dice "No se pudieron cargar las vacantes" | Que el servidor esté arriba y que `SITIOS_PERMITIDOS` incluya el dominio exacto de la página (con y sin `www`). |
| Se perdió la clave del administrador | Otro administrador la cambia en `/admin`. Si no hay otro, contactar al desarrollador. |

## Desarrollo local

```bash
cp .env.example .env
docker compose up -d --build
```

Panel en `http://localhost:5001/talento-humano`. La página pública abierta con
Live Server de VS Code (`http://127.0.0.1:5500/pages/empleo.html`) lee las vacantes
de este servidor local.
