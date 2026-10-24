"""Comprueba que los tests de los arreglos **siguen detectando** el defecto.

POR QUÉ ESTA PUERTA
-------------------
Un test que no puede demostrar que detecta lo que dice detectar no es un
test: es una línea de texto que dice "OK". Con los arreglos de esta tanda
(T-113, T-121, T-122, T-125, T-129...T-134) hay **once** regresiones que
sólo se ven si alguien vuelve a poner el defecto.

Mientras la prueba inversa vivía en la carpeta temporal de quien la
escribió, nadie la ejecutaba: los tests podían dejar de detectar (por un
refactor, un cambio de mensaje o un test reescrito) y el repo se
quedaría en verde sin que nadie se enterase. Esta puerta las ejecuta
**todas**, cada vez, y falla si alguna deja de detectar.

CÓMO FUNCIONA
--------------
Para cada caso: se copia el **backend entero** a un directorio temporal,
se vuelve a poner el defecto **en la copia**, se ejecuta el test allí y
se comprueba que **falla** (y que falla por una aserción, no por un
error de código: un ``NameError`` en el defecto probaría que el test se
rompe, no que detecta).

OJO (2026-10-23): la primera versión modificaba el fichero **en su
sitio**, y se discovered al running el CI en paralelo: el job leía el
código con el defecto puesto (y el árbol de trabajo quedaba sucio).
Por eso ahora se trabaja sobre una **copia**: la puerta no toca el
repositorio en absoluto y se puede ejecutar sin miedo junto a otras
cosas.

    python tools/verificar_pruebas_inversas.py
    python tools/verificar_pruebas_inversas.py --autoprueba
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"

#: Lo que se copia al directorio temporal (lo justo para que la suite
#: corra igual que en el repo).
PARA_COPIAR = (
    "app",
    "tests",
    "alembic",
    "alembic.ini",
    "pyproject.toml",
)


@dataclass
class Caso:
    nombre: str
    fichero: str
    cambios: list[tuple[str, str]] = field(default_factory=list)
    test: str = ""


# ── los casos (el defecto y el test que lo debe detectar) ───────────────
CASOS: list[Caso] = [
    Caso(
        nombre="T-113 · el alta de tickets vuelve a aceptar cualquier sucursal",
        fichero="app/api/v1/tickets.py",
        cambios=[
            (
                "    # T-113: la sucursal del body tiene que ser una sucursal del usuario.\n"
                "    parking_context(payload.parking_id, current=user, db=db)\n",
                "",
            ),
        ],
        test="tests/test_aislamiento_sucursal.py::test_alta_de_ticket_en_sucursal_ajena_da_403",
    ),
    Caso(
        nombre="T-114 · una membresia vuelve a convertir a un cliente en gestor",
        fichero="app/core/deps.py",
        cambios=[
            (
                "    # T-114: la membresia no convierte a un cliente en gestor.\n"
                "    if role_value not in ROLES_STAFF:\n"
                "        raise HTTPException(\n"
                "            status_code=status.HTTP_403_FORBIDDEN,\n"
                '            detail="No tiene acceso a esta sucursal",\n'
                "        )\n\n",
                "",
            ),
        ],
        test=(
            "tests/test_aislamiento_sucursal.py::"
            "test_un_cliente_con_membresia_no_gestiona_la_sucursal"
        ),
    ),
    Caso(
        nombre="T-115 · las geocercas vuelven a cruzarse sin la sucursal",
        fichero="app/api/v1/cameras.py",
        cambios=[
            (
                "    # T-115: la camara tiene que ser de la sucursal del path.\n"
                "    _camara_de_sucursal(db, camera_id, parking_id)\n"
                "    return (\n",
                "    return (\n",
            ),
        ],
        test=(
            "tests/test_aislamiento_sucursal.py::"
            "test_no_se_leen_las_geocercas_de_una_camara_de_otra_sucursal"
        ),
    ),
    Caso(
        nombre="T-178 · el rol de la sucursal vuelve a no leerse",
        fichero="app/core/deps.py",
        cambios=[
            (
                "    if _poder_de_rol(rol_a) >= _poder_de_rol(rol_b):\n"
                "        return rol_a\n"
                "    return rol_b\n",
                "    return rol_a\n",
            ),
        ],
        test=(
            "tests/test_rbac_por_sucursal.py::"
            "test_gestor_en_una_sucursal_y_operador_en_otra"
        ),
    ),
    Caso(
        nombre="T-120 · un cliente vuelve a poder cerrar su propio ticket",
        fichero="app/api/v1/tickets.py",
        cambios=[
            (
                "    user: User = Depends(require_role(*ROLES_STAFF)),\n",
                "    user: User = Depends(get_current_user),\n",
            ),
        ],
        test="tests/test_ticket_cierre.py::test_un_cliente_no_puede_cerrar_su_propio_ticket",
    ),
    Caso(
        nombre="T-121 · el cierre manual vuelve a ser un commit a ciegas",
        fichero="app/services/ticket_closing.py",
        cambios=[
            (
                """    actualizados = (
        db.query(Ticket)
        .filter(Ticket.id == ticket.id, Ticket.status == TicketStatus.ACTIVO)
        .update(campos, synchronize_session=False)
    )
    if not actualizados:
        # Otro cierre se ha adelantado: no se toca el ticket.
        db.rollback()
        raise TicketAlreadyClosedError(ticket.id)
    db.commit()
""",
                """    ticket.exit_at = exit_at
    ticket.amount = amount
    ticket.discount = discount
    ticket.total = total
    ticket.status = TicketStatus.CERRADO
    db.commit()
""",
            ),
        ],
        test=(
            "tests/test_ticket_cierre_carrera.py::"
            "test_dos_cierres_a_la_vez_solo_uno_puede_cobrar"
        ),
    ),
    Caso(
        nombre="T-125 · la purga vuelve a borrar los vehiculos con dueño",
        fichero="app/services/vehicle_purge.py",
        cambios=[
            (
                "        .filter(~Vehicle.users.any())\n",
                "",
            ),
        ],
        test="tests/test_purga_vehiculos.py::test_no_borra_un_vehiculo_con_dueno",
    ),
    Caso(
        nombre="T-129 · el original vuelve a guardarse con sus metadatos",
        fichero="app/services/incident_attachments.py",
        cambios=[
            (
                "    contenido_guardado = sanear_metadatos(contenido, mime)\n",
                "    contenido_guardado = contenido\n",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_el_original_servido_no_lleva_metadatos"
        ),
    ),
    Caso(
        nombre="T-131 · el total vuelve a calcularse con los valores sin redondear",
        fichero="app/services/pricing.py",
        cambios=[
            (
                """    amount = round(_compute_amount(tariff, entry_at, exit_at), 2)
    discount = round(
        _compute_discount(db, vehicle_id=vehicle_id, at=exit_at, amount=amount), 2
    )
    total = round(amount - discount, 2)
    return TicketTotal(amount=amount, discount=discount, total=total)
""",
                """    amount = _compute_amount(tariff, entry_at, exit_at)
    discount = _compute_discount(db, vehicle_id=vehicle_id, at=exit_at, amount=amount)
    total = round(amount - discount, 2)
    return TicketTotal(amount=round(amount, 2), discount=round(discount, 2), total=total)
""",
            ),
        ],
        test=(
            "tests/test_pricing_redondeo.py::"
            "test_el_total_cuadra_con_el_importe_menos_el_descuento"
        ),
    ),
    Caso(
        nombre="T-132 · el cliente vuelve a poder invertir el filtro de planes",
        fichero="app/api/v1/plans.py",
        cambios=[
            (
                """    elif not es_admin:
        # Para el resto de roles, el parametro solo puede endurecer el
        # filtro: nunca se ven los planes desactivados.
        only_active = True
""",
                "",
            ),
        ],
        test="tests/test_planes_api.py::test_el_cliente_no_puede_invertir_el_filtro",
    ),
    Caso(
        nombre="T-133 · la guarda de suscripciones vuelve a mirar solo el presente",
        fichero="app/api/v1/plans.py",
        cambios=[
            (
                """    solapada = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.starts_at < ends_at,
            Subscription.ends_at > starts_at,
        )
        .first()
    )
""",
                """    solapada = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.starts_at <= ahora_utc(),
            Subscription.ends_at >= ahora_utc(),
        )
        .first()
    )
""",
            ),
        ],
        test=(
            "tests/test_planes_api.py::"
            "test_no_se_puede_crear_una_suscripcion_que_se_solape_con_otra"
        ),
    ),
    Caso(
        nombre="T-136 · el nombre del fichero vuelve a ir crudo al mensaje de error",
        fichero="app/services/incident_attachments.py",
        cambios=[
            (
                """            detail=(
                f"El fichero '{nombre_seguro(nombre)}' no es una imagen válida "
                "(sólo JPEG, PNG o WebP)"
            ),
""",
                """            detail=(
                f"El fichero '{nombre}' no es una imagen válida "
                "(sólo JPEG, PNG o WebP)"
            ),
""",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_el_nombre_del_fichero_no_rompe_el_mensaje_de_error"
        ),
    ),
    Caso(
        nombre="T-134 · la metadata de un adjunto caducado vuelve a servirse",
        fichero="app/api/v1/incidents.py",
        cambios=[
            (
                """    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    _exigir_no_caducado(adjunto)
    return adjuntos.a_esquema(adjunto)
""",
                """    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    return adjuntos.a_esquema(adjunto)
""",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_la_metadata_de_un_adjunto_caducado_no_se_sirve"
        ),
    ),
    Caso(
        nombre="T-141 · la purga vuelve a dejar huerfano el fichero compartido",
        fichero="app/services/incident_attachments.py",
        cambios=[
            (
                "    ids_a_borrar = {adjunto.id for adjunto in adjuntos}\n",
                "    ids_a_borrar = set()  # T-141 (defecto): las referencias se\n"
                "    # contaban ANTES de borrar las filas, asi que dos adjuntos\n"
                "    # con el mismo hash se veian como referencia mutua y el\n"
                "    # fichero no se borraba nunca.\n",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_dos_adjuntos_que_comparten_el_mismo_fichero_se_purgan_juntos"
        ),
    ),
    Caso(
        nombre="T-141 · la purga vuelve a callar si no ve el volumen",
        fichero="app/services/incident_attachments.py",
        cambios=[
            (
                """    faltantes = 0
    for adjunto in vivos:
        if adjunto.id in ids_a_borrar:
            continue
        for relativa in (adjunto.storage_path, adjunto.thumbnail_path):
            if relativa and not (base / relativa).exists():
                faltantes += 1
""",
                """    faltantes = 0  # T-141 (defecto): sin avisar de que el proceso no ve
    # el volumen compartido, la purga decia «deleted: N» y los ficheros se
    # quedaban en el disco del backend para siempre.
""",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_la_purga_avisa_si_no_ve_el_volumen_de_adjuntos"
        ),
    ),
    Caso(
        nombre="T-142 · la alerta vuelve a fingir que el correo salio",
        fichero="app/services/email.py",
        cambios=[
            (
                """    if not smtp_configurado():
        log.error(
            "send_alert_email: no hay SMTP configurado (SMTP_HOST=%r): el "
            "correo NO se ha enviado (alert=%s)",
            settings.smtp_host,
            alert.id,
        )
        return False
""",
                "",
            ),
        ],
        test=(
            "tests/test_correo_fail_closed.py::"
            "test_en_produccion_sin_smtp_el_alerta_no_dice_que_se_ha_enviado"
        ),
    ),
    Caso(
        nombre="T-142 · el reset de contrasena vuelve a fingir que el correo salio",
        fichero="app/services/password_reset_email.py",
        cambios=[
            (
                """    from app.services.email import smtp_configurado

    if not smtp_configurado():
        log.error(
            "send_password_reset_email: no hay SMTP configurado "
            "(SMTP_HOST=%r): el correo NO se ha enviado (to=%s)",
            settings.smtp_host,
            to_email,
        )
        return False
""",
                "",
            ),
        ],
        test=(
            "tests/test_correo_fail_closed.py::"
            "test_en_produccion_sin_smtp_el_reset_no_dice_que_se_ha_enviado"
        ),
    ),
    Caso(
        nombre="T-143 · el 413 vuelve a llevar el nombre del fichero en crudo",
        fichero="app/api/v1/incidents.py",
        cambios=[
            (
                """                    f\"El fichero \"
                    f\"'{adjuntos.nombre_seguro(upload.filename or 'adjunto')}' \"
                    f\"supera el tamaño máximo ({limite} bytes)\"
""",
                """                    f\"El fichero '{upload.filename or 'adjunto'}' supera el \"
                    f\"tamaño máximo ({limite} bytes)\"
""",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_el_nombre_del_fichero_no_rompe_el_mensaje_de_413"
        ),
    ),
    Caso(
        nombre="T-144 · los adjuntos caducados vuelven a ocupar cupo",
        fichero="app/services/incident_attachments.py",
        cambios=[
            (
                """    ahora = datetime.now(timezone.utc)
    total = 0
    for adjunto in db.query(IncidentAttachment).filter(
        IncidentAttachment.alert_id == alert_id
    ).all():
        caducidad = adjunto.expires_at
        if caducidad is None:
            total += 1
            continue
        if caducidad.tzinfo is None:
            caducidad = caducidad.replace(tzinfo=timezone.utc)
        if caducidad > ahora:
            total += 1
    return total
""",
                """    return db.query(IncidentAttachment).filter(
        IncidentAttachment.alert_id == alert_id
    ).count()
""",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_un_adjunto_caducado_no_ocupa_cupo"
        ),
    ),
    Caso(
        nombre="T-124 · las estancias sin salida vuelven a quedarse abiertas",
        fichero="app/services/ticket_auto_close.py",
        cambios=[
            (
                "        if entrada > corte:\n            continue\n",
                "        if entrada < corte:  # T-124 (defecto): comparacion invertida\n"
                "            continue\n",
            ),
        ],
        test=(
            "tests/test_ticket_auto_close.py::"
            "test_un_ticket_sin_salida_se_cierra_a_las_24_horas"
        ),
    ),
    Caso(
        nombre="T-149 · el correo de la alerta vuelve a perderse si el broker esta caido",
        fichero="app/services/email.py",
        cambios=[
            (
                """        return _enviar_en_linea(
            alert_id=alert_id,
""",
                """        return False  # T-149 (defecto): el correo se pierde en silencio
        return _enviar_en_linea(
            alert_id=alert_id,
""",
            ),
        ],
        test=(
            "tests/test_correo_broker_caido.py::"
            "test_el_correo_sale_en_linea_si_el_broker_esta_caido"
        ),
    ),
    Caso(
        nombre="T-150 · el lock de la ronda vuelve a caducar con la ronda viva",
        fichero="app/workers/tasks.py",
        cambios=[
            (
                """            "then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
            1, clave, token, str(ttl),
        )
        # 0 = el lock ya no es nuestro (caduco, o lo tomo otra ronda).
        return bool(resultado)
""",
                """            "then return redis.call('get', KEYS[1]) else return 0 end",
            1, clave, token, str(ttl),
        )
        # T-150 (defecto): se dice que se ha renovado, pero el TTL no se
        # renueva: la ronda larga pierde el lock con la ronda en marcha.
        return True
""",
            ),
        ],
        test=(
            "tests/test_lock_heartbeats.py::"
            "test_el_lock_se_renueva_mientras_la_ronda_vive"
        ),
    ),
    Caso(
        nombre="T-151 · el worker vuelve a no reentregar las tareas si muere",
        fichero="app/workers/celery_app.py",
        cambios=[
            (
                "    task_reject_on_worker_lost=True,\n",
                "    # T-151 (defecto): sin esto, el mensaje espera al\n"
                "    # visibility_timeout de Redis (1 hora).\n",
            ),
        ],
        test=(
            "tests/test_celery_confiabilidad.py::"
            "test_el_worker_reentrega_las_tareas_si_muere"
        ),
    ),
    Caso(
        nombre="T-152 · el endpoint de health vuelve a restar una fecha naive",
        fichero="app/api/v1/cameras.py",
        cambios=[
            (
                """    # T-152 (2026-10-24): un ``DateTime(timezone=True)`` vuelve **naive**
    # al releerlo de SQLite, y restar un naive de un datetime con zona da
    # ``TypeError`` (un 500). Es el mismo ajuste que hacen el resto de
    # servicios del repo (y que este fichero no hacia).
    if last_at is not None and last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
""",
                "",
            ),
        ],
        test=(
            "tests/test_camera_health_api.py::test_health_con_fecha_naive_no_da_500"
        ),
    ),
    Caso(
        nombre="T-153 · el informe de alertas vuelve a traer todas las filas",
        fichero="app/services/reports.py",
        cambios=[
            (
                """        .limit(MAX_FILAS_INFORME + 1)
        .all()
    )
    _acotar_filas(alertas)
""",
                """        .all()
    )
""",
            ),
        ],
        test=(
            "tests/test_informe_alertas_tope.py::"
            "test_el_informe_de_alertas_rechaza_una_ventana_demasiado_grande"
        ),
    ),
    Caso(
        nombre="T-156 · la purga de vehiculos vuelve a cargar la tabla entera",
        fichero="app/services/vehicle_purge.py",
        cambios=[
            (
                """    if limite is not None:
        consulta = consulta.limit(limite)
""",
                "",
            ),
        ],
        test=(
            "tests/test_purga_vehiculos.py::"
            "test_la_purga_trae_los_vehiculos_en_lotes"
        ),
    ),
    Caso(
        nombre="T-159 · el alta del cliente vuelve a no normalizar la matricula",
        fichero="app/api/v1/users.py",
        cambios=[
            (
                "        plate=normalizar_matricula(payload.plate),\n",
                "        plate=payload.plate.strip().upper(),\n",
            ),
        ],
        test=(
            "tests/test_normalizacion_matricula.py::"
            "test_el_alta_del_cliente_normaliza_la_matricula"
        ),
    ),
    Caso(
        nombre="T-163 · la sucursal desactivada vuelve a admitir entradas",
        fichero="app/services/ingest_service.py",
        cambios=[
            (
                """    parking = db.get(Parking, camera.parking_id)
    if parking is not None and not parking.is_active:
        log.warning(
            "ingest: sucursal %s desactivada, se omite (plate=%s camera=%s)",
            camera.parking_id,
            hit.plate,
            camera.id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_PARKING_INACTIVE,
            confidence=hit.confidence,
            reason="Sucursal desactivada; no se admiten entradas",
        )

""",
                "",
            ),
        ],
        test=(
            "tests/test_ingest_service.py::"
            "test_una_sucursal_desactivada_no_admite_entradas"
        ),
    ),
    Caso(
        nombre="T-164 · la camara que dejo de empujar deja de detectarse",
        fichero="app/services/camera_push_watch.py",
        cambios=[
            (
                "        if ultimo is None or ultimo < corte:\n",
                "        if False:  # T-164 (defecto)\n",
            ),
        ],
        test=(
            "tests/test_camera_push_watch.py::"
            "test_una_camara_que_no_empuja_nada_se_detecta"
        ),
    ),

    Caso(
        nombre="T-166 · el push externo vuelve a persistir la basura del OCR",
        fichero="app/api/v1/plates.py",
        cambios=[
            (
                """    hits_validos: list[PlateHit] = []
    for hit in payload.hits:
        if not parece_matricula(hit.plate):
            log.warning(
                "plates: el OCR no leyó una matrícula (no se persiste): %r",
                hit.plate,
                extra={"camera_id": camera.id},
            )
            continue
        hits_validos.append(hit)
""",
                """    hits_validos: list[PlateHit] = list(payload.hits)
""",
            ),
        ],
        test=(
            "tests/test_plates_push_filtrado.py::"
            "test_el_push_no_persiste_una_lectura_que_no_es_matricula"
        ),
    ),
    Caso(
        nombre="T-167 · la ventana del contador de fallos vuelve a anclarse en el primero",
        fichero="app/services/alerts.py",
        cambios=[
            (
                """        count = cast(int, rds.incr(_consecutive_key(camera.id)))
        # T-167: el TTL se renueva en **cada** fallo. Antes sólo se
        # ponía en el primero (``if count == 1``), o sea que la ventana
        # iba desde el primer fallo: si los fallos llegaban más
        # espaciados que TTL/umbral, el contador caducaba antes de
        # poder llegar al umbral y la alerta NUNCA saltaba.
        rds.expire(_consecutive_key(camera.id), ttl)
""",
                """        count = cast(int, rds.incr(_consecutive_key(camera.id)))
        if count == 1:
            rds.expire(_consecutive_key(camera.id), ttl)
""",
            ),
        ],
        test=(
            "tests/test_alerta_ocr_ventana.py::"
            "test_una_serie_de_fallos_mas_espaciada_que_el_umbral_dispara_la_alerta"
        ),
    ),
    Caso(
        nombre="T-168 · el directorio de respaldo de los frames vuelve a no limpiarse",
        fichero="app/workers/tasks.py",
        cambios=[
            (
                """    for directorio in (DEFAULT_OCR_FAILED_DIR, FALLBACK_OCR_FAILED_DIR):
        if not directorio.exists():
            continue
        for entry in directorio.iterdir():
            if not entry.is_file():
                continue
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                try:
                    entry.unlink()
                    deleted += 1
                except OSError as exc:
                    log.warning("No se pudo borrar %s: %s", entry, exc)
            else:
                kept += 1
""",
                """    if not DEFAULT_OCR_FAILED_DIR.exists():
        return {"deleted": 0, "kept": 0}
    for entry in DEFAULT_OCR_FAILED_DIR.iterdir():
        if not entry.is_file():
            continue
        mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            try:
                entry.unlink()
                deleted += 1
            except OSError as exc:
                log.warning("No se pudo borrar %s: %s", entry, exc)
        else:
            kept += 1
""",
            ),
        ],
        test=(
            "tests/test_limpieza_frames_ocr.py::"
            "test_la_tarea_limpia_el_directorio_de_respaldo"
        ),
    ),

]


def _copiar_backend(destino: Path) -> None:
    """Copia lo justo del backend para que la suite corra igual."""
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in PARA_COPIAR:
        origen = BACKEND / nombre
        if origen.is_dir():
            shutil.copytree(
                origen,
                destino / nombre,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
            )
        elif origen.is_file():
            shutil.copy2(origen, destino / nombre)


def _aplicar(copia: Path, caso: Caso) -> bool:
    """Pone el defecto **en la copia**. False si el bloque no aparece."""
    ruta = copia / caso.fichero
    texto = ruta.read_text(encoding="utf-8")
    for viejo, nuevo in caso.cambios:
        if texto.count(viejo) != 1:
            print(f"      el bloque aparece {texto.count(viejo)} veces (se esperaba 1)")
            return False
        texto = texto.replace(viejo, nuevo)
    ruta.write_text(texto, encoding="utf-8", newline="")
    return True


def _ejecutar(copia: Path, test: str) -> tuple[int, str]:
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "--tb=line",
            "-p", "no:cacheprovider", test,
        ],
        cwd=copia,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fallo_real(salida: str, test: str) -> bool:
    """El fallo es una asercion del test (no un error de codigo)."""
    nombre = test.split("::")[-1]
    if "FAILED" not in salida or nombre not in salida:
        return False
    return not (
        "NameError" in salida or "SyntaxError" in salida or "ImportError" in salida
    )


def verificar() -> int:
    fallos: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pruebas_inversas_") as temporal:
        copia = Path(temporal) / "backend"
        _copiar_backend(copia)
        for caso in CASOS:
            # El fichero vuelve a su estado (por si un caso anterior lo
            # toco) antes de aplicar el defecto.
            shutil.copy2(BACKEND / caso.fichero, copia / caso.fichero)
            if not _aplicar(copia, caso):
                print(f"  [FALLA] {caso.nombre}: no se pudo poner el defecto")
                fallos.append(caso.nombre)
                continue
            codigo, salida = _ejecutar(copia, caso.test)
            if codigo == 0:
                print(f"  [FALLA] {caso.nombre}: el test PASA con el defecto")
                fallos.append(caso.nombre)
            elif not _fallo_real(salida, caso.test):
                print(
                    f"  [FALLA] {caso.nombre}: el test falla, pero no por una "
                    f"aserción (eso no prueba que detecte)"
                )
                fallos.append(caso.nombre)
            else:
                print(f"  [OK   ] {caso.nombre}")

    print()
    if fallos:
        print(f"{len(fallos)} prueba(s) inversa(s) que ya NO detectan su defecto:")
        for nombre in fallos:
            print(f"  - {nombre}")
        return 1
    print(f"Las {len(CASOS)} pruebas inversas siguen detectando su defecto.")
    return 0


def _autoprueba() -> int:
    """La puerta tiene que **detectar** un caso que no detecta nada.

    Se monta un caso de mentira: un "defecto" que **no** rompe el
    comportamiento (un comentario), con un test que sigue pasando. La
    puerta tiene que decir que ese caso no detecta.
    """
    with tempfile.TemporaryDirectory(prefix="autoprueba_") as temporal:
        raiz = Path(temporal)
        (raiz / "backend" / "app").mkdir(parents=True)
        (raiz / "backend" / "tests").mkdir(parents=True)
        (raiz / "backend" / "app" / "ejemplo.py").write_text("# original\n", encoding="utf-8")
        (raiz / "backend" / "tests" / "ejemplo.py").write_text(
            "def test_nada():\n    assert True\n", encoding="utf-8"
        )
        codigo, _salida = _ejecutar(raiz / "backend", "tests/ejemplo.py::test_nada")
        if codigo == 0:
            print("  OK: la puerta detecta el caso que no detecta nada")
        else:
            print(f"  FALLO: la puerta no vio el caso de mentira (codigo {codigo})")
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="comprueba que la puerta detecta un caso que no detecta nada",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return _autoprueba()

    print(
        f"Comprobando {len(CASOS)} pruebas inversas (con el defecto puesto, "
        f"en una copia del backend)...\n"
    )
    return verificar()


if __name__ == "__main__":
    sys.exit(main())
