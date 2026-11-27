"""
Permisos por rol de la app: quién puede hacer qué con un veredicto.

Se comprueban en el servidor justo antes de guardar (desactivar un botón en pantalla no basta).
Roles (src/auth.py): revisor · auditor · admin.
"""
import config

PERMISOS = {
    "aprobar": ("revisor", "auditor", "admin"),    # confirmar el veredicto que propone la IA
    "corregir": ("auditor", "admin"),              # cambiarlo por otro distinto
}


def restringido() -> bool:
    """¿Se aplican los permisos por rol? Solo cuando el inicio de sesión comprueba de verdad quién entra.
    En modo demo (AUTH_ACTIVADA=false) y en modo prototipo (AUTH_PROTOTIPO=true) cualquiera puede decir que es
    cualquiera, así que el rol todavía no demuestra nada y no se restringe."""
    return config.AUTH_ACTIVADA and not config.AUTH_PROTOTIPO


def puede(usuario: dict, accion: str) -> bool:
    if not restringido():
        return True
    return usuario.get("rol") in PERMISOS[accion]
