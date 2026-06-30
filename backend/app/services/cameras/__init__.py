"""Servicios de cámaras (captura RTSP, ONVIF, calibración).

En MVP sólo se usa la captura: `app.services.cameras.capture.grab_frame`.
El driver es OpenCV (opencv-python-headless), ejecutado en
`asyncio.to_thread` para no bloquear el event loop de Celery.
"""