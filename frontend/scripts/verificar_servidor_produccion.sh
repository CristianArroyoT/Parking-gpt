#!/bin/sh
# Comprueba, DENTRO del contenedor de producción del frontend, los tres
# requisitos que el README (§ PWA) le exige al servidor estático:
#
#   1. El manifiesto con ``Content-Type: application/manifest+json``.
#   2. El service worker SIN caché (si el navegador lo cachea, sigue
#      ejecutando la versión vieja).
#   3. El ``index.html`` sin caché (para que un despliegue nuevo se vea).
#
# Y un cuarto, que no estaba en el README pero importa igual: el bundle
# tiene que servirse **como JavaScript**. Con el ``content-type``
# equivocado el navegador no lo ejecuta y la app no arranca.
#
# Se ejecuta DENTRO del contenedor (usa el ``wget`` de busybox):
#     docker cp frontend/scripts/verificar_servidor_produccion.sh <cont>:/tmp/v.sh
#     docker exec <cont> sh /tmp/v.sh
set -eu

BASE="${1:-http://127.0.0.1}"
fallos=0

cabeceras() {
    wget -S -O /dev/null "$1" 2>&1
}

comprobar() {
    patron="$1"
    url="$2"
    descripcion="$3"
    if cabeceras "$url" | grep -qi "$patron"; then
        echo "  OK  $descripcion"
    else
        echo "  FALLO  $descripcion: en $url no aparece '$patron'"
        fallos=$((fallos + 1))
    fi
}

echo "Requisitos del servidor de produccion ($BASE):"

comprobar 'content-type:.*application/manifest+json' \
    "$BASE/manifest.webmanifest" \
    "el manifiesto con su content-type"

comprobar 'cache-control:.*no-store' \
    "$BASE/sw.js" \
    "el service worker sin cache"

comprobar 'cache-control:.*no-cache' \
    "$BASE/index.html" \
    "el index.html sin cache"

# El bundle: tiene que servirse como JavaScript, no como
# application/octet-stream (que el navegador no ejecuta).
asset=$(grep -o '/assets/index-[^"]*\.js' /usr/share/nginx/html/index.html | head -1 || true)
if [ -n "$asset" ]; then
    comprobar 'content-type:.*application/javascript' \
        "$BASE$asset" \
        "el bundle ($asset) como JavaScript"
else
    echo "  FALLO  no se encuentra el bundle en el index.html"
    fallos=$((fallos + 1))
fi

# Y la ruta de la SPA: una ruta profunda debe devolver el shell.
comprobar 'content-type:.*text/html' \
    "$BASE/mis-tickets" \
    "el fallback de la SPA en una ruta profunda"

if [ "$fallos" -gt 0 ]; then
    echo "FALLAN $fallos requisito(s) del servidor de produccion."
    exit 1
fi
echo "El servidor de produccion cumple los requisitos del PWA."
