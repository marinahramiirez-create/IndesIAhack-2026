"""
NIMBUS · auditoría de cumplimiento del reto real de Airbus (IndesIAhack 2026).

Una orden: carpeta de PDF → respuestas.csv (documento, ubicacion, tipo, clausula, justificacion).
    python -m nimbus.ejecutar RUTA_A_LA_CARPETA_DE_PDF [--salida respuestas.csv]

Capas (cada una recibe y devuelve datos con esquema, ver nimbus/modelos.py):
    ingesta.py        PDF → Documento (texto, secciones, requisitos, tablas, figuras, ¿escaneado?)
    conocimiento.py   referencias: estándar STD-SEC-001 vigente, lista maestra (vigencias), Part-IS
    detectores/       reglas genéricas que proponen hallazgos (prosa, parámetros, referencias...)
    salida.py         validación del formato y escritura progresiva del CSV
    ejecutar.py       orquestación: un proceso por documento, en paralelo, tolerante a fallos
"""
