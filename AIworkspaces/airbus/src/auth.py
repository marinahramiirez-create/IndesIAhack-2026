"""
Inicio de sesión de la app Airbus.

Dos formas de entrar, ambas guardadas en la MISMA tabla `usuarios` (src/db.py):
  1. Usuario + contraseña (cuentas locales). La contraseña nunca se guarda: solo su hash PBKDF2-SHA256.
  2. "Iniciar sesión con Microsoft" (Microsoft Entra ID, OpenID Connect). La contraseña y la MFA con
     Microsoft Authenticator las pide Microsoft en su página; la app solo recibe quién es (claims tid/oid).
     Se activa sola cuando existe .streamlit/secrets.toml con la sección [auth] y está instalado Authlib
     (ver AUTENTICACION.md). Mientras tanto el botón aparece desactivado.

Gestión de cuentas locales desde la terminal (dentro de airbus/, con el entorno activado):
    python -m src.auth crear --login sergio --nombre "Sergio" --rol admin     (pide la contraseña)
    python -m src.auth password --login sergio                                (cambiar contraseña)
    python -m src.auth listar
"""
import hashlib
import hmac
import html
import secrets
import time
from datetime import datetime

import config
from src import db

ROLES = ("revisor", "auditor", "admin")
ITERACIONES = 600_000          # recomendación OWASP para PBKDF2-SHA256
MIN_LONGITUD = 8
CLAVE_SESION = "usuario_sesion"

TXT = {
    "es": {
        "titulo": "Iniciar sesión", "sub": "Auditoría de cumplimiento Part-IS · acceso restringido al equipo auditor",
        "usuario": "Usuario", "password": "Contraseña", "entrar": "Entrar",
        "o": "o", "ms": "Iniciar sesión con Microsoft",
        "ms_off": "Inicio de sesión con Microsoft pendiente de configurar en Azure (ver AUTENTICACION.md).",
        "error": "Usuario o contraseña incorrectos.", "vacio": "Escribe usuario y contraseña.",
        "espera": "Demasiados intentos fallidos. Espera {s} s y vuelve a probar.",
        "sin_usuarios": "Todavía no hay ninguna cuenta. Créala desde la terminal, dentro de la carpeta airbus/:",
        "inactivo": "Tu cuenta está desactivada. Contacta con un administrador.",
        "salir": "Cerrar sesión", "sesion": "Sesión", "via_ms": "Microsoft", "via_local": "usuario y contraseña",
        "prototipo": "Modo prototipo: entra con cualquier usuario y contraseña. Todavía no se comprueban.",
        "via_proto": "prototipo",
    },
    "en": {
        "titulo": "Sign in", "sub": "Part-IS compliance audit · restricted to the audit team",
        "usuario": "Username", "password": "Password", "entrar": "Sign in",
        "o": "or", "ms": "Sign in with Microsoft",
        "ms_off": "Microsoft sign-in is pending configuration in Azure (see AUTENTICACION.md).",
        "error": "Wrong username or password.", "vacio": "Enter username and password.",
        "espera": "Too many failed attempts. Wait {s} s and try again.",
        "sin_usuarios": "There are no accounts yet. Create one from the terminal, inside the airbus/ folder:",
        "inactivo": "Your account is disabled. Contact an administrator.",
        "salir": "Sign out", "sesion": "Session", "via_ms": "Microsoft", "via_local": "username and password",
        "prototipo": "Prototype mode: sign in with any username and password. They are not checked yet.",
        "via_proto": "prototype",
    },
}


# --------------------------------------------------------------------------- contraseñas
def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal.hex()}${h.hex()}"


def verificar_password(password: str, guardado: str | None) -> bool:
    try:
        algoritmo, it, sal, h = (guardado or "").split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(calc.hex(), h)          # comparación en tiempo constante
    except ValueError:
        return False


# Hash de relleno: si el usuario no existe se verifica igualmente, para no delatar por el tiempo de respuesta
_HASH_FALSO = hash_password(secrets.token_hex(8))


def autenticar_local(login: str, password: str) -> dict | None:
    """Devuelve el usuario si usuario+contraseña son correctos y la cuenta está activa; si no, None."""
    u = db.buscar_por_login(login) if login else None
    ok = verificar_password(password, u["password_hash"] if u and u["password_hash"] else _HASH_FALSO)
    if not (u and ok and u["password_hash"]):
        return None
    return u


def _entrar_prototipo(login: str) -> dict:
    """MODO PROTOTIPO (AUTH_PROTOTIPO=true): no se comprueba la contraseña. Se usa la cuenta con ese
    usuario o se crea una sin contraseña (así no podrá entrar cuando se apague el modo prototipo)."""
    u = db.buscar_por_login(login)
    if not u:
        nombre = login.strip().split("@")[0].replace(".", " ").replace("_", " ").title()   # sergio.diaz → Sergio Diaz
        db.crear_usuario_local(login, nombre, None, "revisor", login.strip().lower() if "@" in login else None)
        u = db.buscar_por_login(login)
    return u


# --------------------------------------------------------------------------- Microsoft Entra ID
def microsoft_configurado() -> bool:
    """True si hay [auth] en .streamlit/secrets.toml y Authlib instalado (requisitos de st.login)."""
    import streamlit as st
    try:
        import authlib  # noqa: F401
        return "auth" in st.secrets
    except Exception:          # sin secrets.toml o sin Authlib
        return False


def _usuario_microsoft() -> dict | None:
    """Si el usuario volvió de la página de Microsoft, lo vincula/crea en la BD por (tid, oid)."""
    import streamlit as st
    if not (microsoft_configurado() and st.user.is_logged_in):
        return None
    roles = st.user.get("roles") or []
    rol = next((r for r in ("admin", "auditor", "revisor") if r in roles), None)
    return db.obtener_o_crear_usuario_entra(
        tid=st.user.get("tid"), oid=st.user.get("oid"),
        nombre=st.user.get("name") or st.user.get("preferred_username") or "Microsoft",
        email=st.user.get("preferred_username") or st.user.get("email"), rol=rol)


# --------------------------------------------------------------------------- pantalla de login
def _sesion(u: dict, via: str) -> dict:
    return {"id": u["id"], "nombre": u["nombre"], "login": u.get("login"), "email": u.get("email"),
            "rol": u["rol"], "via": via, "desde": datetime.now().strftime("%H:%M")}


def requerir_login(lang: str = "es") -> dict:
    """Llamar al principio de app.py. Devuelve el usuario con sesión iniciada;
    si no hay sesión, dibuja la pantalla de login y detiene la app (st.stop)."""
    import streamlit as st
    db.inicializar()

    if not config.AUTH_ACTIVADA:     # modo demo sin login
        uid = db.obtener_usuario_local()
        return {"id": uid, "nombre": db.USUARIO_LOCAL, "login": None, "rol": "revisor", "via": "local"}

    s = st.session_state.get(CLAVE_SESION)
    if s:
        u = db.buscar_por_id(s["id"])
        if u and u["activo"]:
            return s
        st.session_state.pop(CLAVE_SESION, None)       # cuenta borrada o desactivada → fuera

    t = TXT[lang]
    u_ms = _usuario_microsoft()
    if u_ms:
        if not u_ms["activo"]:
            st.error(t["inactivo"])
            st.button(t["salir"], on_click=st.logout)
            st.stop()
        st.session_state[CLAVE_SESION] = _sesion(u_ms, "microsoft")
        return st.session_state[CLAVE_SESION]

    _pantalla_login(t)
    st.stop()


def _pantalla_login(t: dict):
    import streamlit as st
    _, centro, _ = st.columns([1, 1.3, 1])
    with centro:
        st.markdown(f"<div class='hero'><div class='eyebrow'>EASA Part-IS</div><h1>{t['titulo']}</h1>"
                    f"<div class='rule'></div><div class='sub'>{t['sub']}</div></div>", unsafe_allow_html=True)

        hay_locales = not db.leer_df("SELECT 1 FROM usuarios WHERE password_hash IS NOT NULL LIMIT 1").empty
        if config.AUTH_PROTOTIPO:
            st.info(t["prototipo"], icon=":material/science:")
        elif not hay_locales and not microsoft_configurado():
            st.warning(t["sin_usuarios"])
            st.code('python -m src.auth crear --login TU_USUARIO --nombre "Tu nombre" --rol admin')

        bloqueo = st.session_state.get("login_bloqueo_hasta", 0) - time.time()
        with st.form("login", clear_on_submit=False):
            login = st.text_input(t["usuario"], autocomplete="username")
            password = st.text_input(t["password"], type="password", autocomplete="current-password")
            enviar = st.form_submit_button(t["entrar"], type="primary", width="stretch")
        if enviar:
            if bloqueo > 0:
                st.error(t["espera"].format(s=int(bloqueo) + 1))
            elif not login or not password:
                st.warning(t["vacio"])
            else:
                u = _entrar_prototipo(login) if config.AUTH_PROTOTIPO else autenticar_local(login, password)
                if u and not u["activo"]:
                    st.error(t["inactivo"])
                elif u:
                    db.marcar_acceso(u["id"])
                    st.session_state.pop("login_fallos", None)
                    st.session_state[CLAVE_SESION] = _sesion(u, "prototipo" if config.AUTH_PROTOTIPO else "local")
                    st.rerun()
                else:
                    fallos = st.session_state.get("login_fallos", 0) + 1
                    st.session_state.login_fallos = fallos
                    if fallos >= 5:                       # tras 5 fallos seguidos, 30 s de espera
                        st.session_state.login_bloqueo_hasta = time.time() + 30
                        st.session_state.login_fallos = 0
                    st.error(t["error"])

        st.markdown(f"<div style='text-align:center;color:#5B6B82;margin:6px 0'>— {t['o']} —</div>",
                    unsafe_allow_html=True)
        if microsoft_configurado():
            st.button(t["ms"], icon=":material/login:", on_click=st.login, width="stretch")
        else:
            st.button(t["ms"], icon=":material/login:", disabled=True, width="stretch", help=t["ms_off"])
            st.caption(t["ms_off"])


def _iniciales(nombre: str) -> str:
    partes = [p for p in nombre.replace(".", " ").replace("_", " ").split() if p]
    return ("".join(p[0] for p in partes[:2]) or "?").upper()


def mostrar_sesion(usuario: dict, lang: str = "es"):
    """Barra lateral: tarjeta del usuario arriba y "Cerrar sesión" fijo abajo del todo.
    Lo que se añada a la barra lateral después (filtros, etc.) queda entre los dos."""
    import streamlit as st
    if not config.AUTH_ACTIVADA:
        return
    t = TXT[lang]
    via = {"microsoft": t["via_ms"], "prototipo": t["via_proto"]}.get(usuario["via"], t["via_local"])
    ident = usuario.get("email") or usuario.get("login") or ""
    e = html.escape
    st.markdown("""<style>
  /* con barra lateral, la franja superior de Streamlit (botón >> para abrirla) tapaba el selector ES · EN:
     se baja el contenido lo justo para que quede siempre visible */
  [data-testid="stMain"] [data-testid="stMainBlockContainer"] { padding-top: 3.6rem; }
  /* la columna de la barra lateral ocupa todo el alto; el botón de salir se va al final */
  [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
      min-height: calc(100vh - 7rem); }
  [data-testid="stSidebar"] .st-key-cerrar_sesion { order: 999; margin-top: auto; }
  .usr { background:#fff; border:1px solid #D5DEEA; border-radius:14px; padding:18px 16px 14px; text-align:center;
         box-shadow:0 1px 2px rgba(20,40,75,.06); }
  .usr .av { width:64px; height:64px; border-radius:50%; background:#14284B; color:#fff; display:grid;
             place-items:center; font-weight:800; font-size:1.5rem; margin:0 auto 10px; border:3px solid #009FE3; }
  .usr .nm { font-weight:700; color:#14284B; font-size:1.08rem; line-height:1.2; word-break:break-word; }
  .usr .id { color:#5B6B82; font-size:.82rem; margin-top:2px; word-break:break-all; }
  .usr .rl { display:inline-block; background:#E6F4FB; color:#0077B0; border-radius:999px; padding:2px 12px;
             font-size:.78rem; font-weight:700; margin-top:10px; text-transform:capitalize; }
  .usr .mt { color:#5B6B82; font-size:.78rem; margin-top:10px; border-top:1px solid #E3EAF3; padding-top:8px; }
</style>""", unsafe_allow_html=True)
    with st.sidebar:
        st.markdown(f"""<div class="usr">
  <div class="av">{e(_iniciales(usuario['nombre']))}</div>
  <div class="nm">{e(usuario['nombre'])}</div>
  <div class="id">{e(ident)}</div>
  <div class="rl">{e(usuario['rol'])}</div>
  <div class="mt">{e(t['sesion'])}: {e(via)} · {e(usuario.get('desde', ''))}</div>
</div>""", unsafe_allow_html=True)
        if st.button(t["salir"], icon=":material/logout:", width="stretch", key="cerrar_sesion"):
            st.session_state.pop(CLAVE_SESION, None)
            if usuario["via"] == "microsoft":
                st.logout()
            st.rerun()


# --------------------------------------------------------------------------- terminal
def _pedir_password() -> str:
    import getpass
    while True:
        p1 = getpass.getpass("Contraseña (no se ve al escribir): ")
        if len(p1) < MIN_LONGITUD:
            print(f"  Mínimo {MIN_LONGITUD} caracteres.")
            continue
        if p1 != getpass.getpass("Repite la contraseña: "):
            print("  No coinciden.")
            continue
        return p1


def main():
    import argparse
    p = argparse.ArgumentParser(description="Cuentas locales de la app Airbus")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear", help="crear una cuenta")
    c.add_argument("--login", required=True)
    c.add_argument("--nombre", required=True)
    c.add_argument("--rol", choices=ROLES, default="revisor")
    c.add_argument("--email")
    pw = sub.add_parser("password", help="cambiar la contraseña")
    pw.add_argument("--login", required=True)
    sub.add_parser("listar", help="ver las cuentas")
    a = p.parse_args()

    db.inicializar()
    if a.cmd == "crear":
        if db.buscar_por_login(a.login):
            raise SystemExit(f"Ya existe el usuario '{a.login}'.")
        db.crear_usuario_local(a.login, a.nombre, hash_password(_pedir_password()), a.rol, a.email)
        print(f"Cuenta '{a.login.lower()}' creada con rol {a.rol}.")
    elif a.cmd == "password":
        u = db.buscar_por_login(a.login)
        if not u:
            raise SystemExit(f"No existe el usuario '{a.login}'.")
        db.cambiar_password(u["id"], hash_password(_pedir_password()))
        print("Contraseña cambiada.")
    else:
        print(db.leer_df("SELECT login, nombre, rol, activo, proveedor, "
                         "CASE WHEN entra_oid IS NULL THEN 'no' ELSE 'sí' END AS microsoft, ultimo_acceso "
                         "FROM usuarios ORDER BY creado").to_string(index=False))


if __name__ == "__main__":
    main()
