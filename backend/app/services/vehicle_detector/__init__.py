"""Cliente HTTP contra el servicio vehicle-detector (YOLO en ``vehicle-detector:8800``).

Réplica exacta del patrón de ``app.services.ocr.client``:
- Timeout corto configurable.
- NUNCA lanza excepción — devuelve ``[]`` ante timeout/JSON inválido/404.
- Singleton lazy + ``reset_vehicle_detector_client()`` para tests con MockTransport.
"""