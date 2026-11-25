# Inicio de sesión: usuario + contraseña y Microsoft (Entra ID)

## Estado

> **Ahora mismo está en MODO PROTOTIPO** (`AUTH_PROTOTIPO=true`, valor por defecto): cualquier usuario y
> contraseña entran, para poder enseñar la app mientras no hay datos ni cuentas reales. Se crea un usuario
> sin contraseña con ese nombre, para que sus decisiones queden firmadas.
> **Para comprobar contraseñas de verdad:** `AUTH_PROTOTIPO=false` en `.env` y crear las cuentas (ver abajo).

| Parte | Estado |
|---|---|
| Pantalla de login con **usuario y contraseña** | ✅ Hecho (`src/auth.py`) |
| Tabla `usuarios` y decisiones firmadas por quien las toma | ✅ Hecho (`src/db.py`) |
| Botón **"Iniciar sesión con Microsoft"** (OpenID Connect) | 🟡 Programado, **desactivado** hasta registrar la app en Azure |
| MFA con **Microsoft Authenticator** | 🟡 Lo exige Entra ID (no se programa); pendiente de configurar en Azure |
| Recursos en Azure (registro de app, roles, acceso condicional) | ⛔ No creados. Requieren autorización y permisos en el inquilino |

## Cómo se usa (local)

Con el entorno activado, dentro de `airbus/`:
```powershell
python -m src.auth crear --login sergio --nombre "Sergio" --rol admin   # pide la contraseña (mín. 8)
python -m src.auth listar
python -m src.auth password --login sergio                              # cambiar contraseña
python -m streamlit run app.py                                          # aparece el login
```
- Roles: `revisor` · `auditor` · `admin` (de momento solo se muestran; los permisos por rol están en la lista de tareas).
- Demo rápida sin login: `AUTH_ACTIVADA=false` en `.env`.
- Cada decisión (aprobar / corregir) queda guardada con el `usuario_id` de quien la tomó.

### Seguridad de las cuentas locales
- La contraseña **nunca** se guarda: solo un hash PBKDF2-SHA256 con sal aleatoria y 600 000 iteraciones (librería estándar de Python).
- Comparación en tiempo constante; si el usuario no existe se calcula igualmente un hash (no se delata por el tiempo).
- Mensaje de error genérico ("usuario o contraseña incorrectos").
- Tras 5 fallos seguidos, 30 s de espera.
- Cuenta desactivada (`activo = false`) → no puede entrar y, si tenía sesión, la pierde.
- La sesión vive en el servidor de Streamlit: al recargar la página (F5) hay que volver a entrar.

## Base de datos (`src/db.py`)

Tabla **`usuarios`**: una persona = una fila, entre por donde entre.

| Columna | Para qué |
|---|---|
| `id` | UUID **interno**. Todas las relaciones apuntan aquí, nunca al correo ni a Microsoft |
| `login`, `password_hash` | Cuenta local. Vacíos si la persona solo entra con Microsoft |
| `nombre`, `email` | Datos visibles. El correo puede cambiar → **no** es clave |
| `rol` | `revisor` · `auditor` · `admin`. Con Microsoft, se copia de los *App Roles* del token en cada acceso |
| `activo` | Dar de baja sin borrar el historial |
| `proveedor` | Cómo se creó: `local` · `entra` |
| `entra_tid`, `entra_oid` | Claims `tid` (inquilino) y `oid` (persona) del token de Microsoft: identificador **estable**. Únicos en pareja |
| `creado`, `ultimo_acceso` | Auditoría |

**Vinculación:** la primera vez que alguien entra con Microsoft, si ya existe una cuenta local con su mismo correo,
se vincula a esa fila (mismas decisiones). Después se le reconoce siempre por `(tid, oid)`.

`decisiones.usuario_id → usuarios.id`. Las BD antiguas se actualizan solas al arrancar; nunca se borra una decisión.

## Activar "Iniciar sesión con Microsoft" (cuando se autorice)

**Flujo** (OpenID Connect, *Authorization Code*): botón → página de Microsoft (cuenta + contraseña + Microsoft
Authenticator) → vuelve a la app con un ID token → `src/auth.py` busca/crea el usuario por `(tid, oid)`.
La app **nunca** ve la contraseña de Microsoft.

1. **Azure** (quien tenga permisos en el inquilino; en el hackathon es el de IndesIA → preguntar antes):
   ```powershell
   az login
   az ad app create --display-name "Auditoria-EASA" --sign-in-audience AzureADMyOrg --web-redirect-uris http://localhost:8501/oauth2callback
   az ad sp create --id <appId>
   az ad app credential reset --id <appId> --display-name streamlit   # devuelve el secreto
   ```
   Además, en el portal de Entra: *App Roles* `revisor`, `auditor`, `admin` y asignar personas o grupos;
   y una política de **Acceso condicional** que exija MFA (Microsoft Authenticator) para esta app.
2. **Dependencia:** `python -m pip install "streamlit[auth]"` (instala Authlib) y añadirla a `requirements.txt`.
3. **Secretos** en `.streamlit/secrets.toml` (ya está en `.gitignore`, **nunca** a git):
   ```toml
   [auth]
   redirect_uri = "http://localhost:8501/oauth2callback"
   cookie_secret = "<cadena aleatoria larga>"
   client_id = "<Application (client) ID>"
   client_secret = "<secreto del paso 1>"
   server_metadata_url = "https://login.microsoftonline.com/<TENANT_ID>/v2.0/.well-known/openid-configuration"
   ```
4. Reiniciar la app: el botón se activa solo (no hay que tocar código).

## Pendiente (siguientes pasos)
1. Permisos por rol (p. ej. solo `auditor`/`admin` pueden corregir veredictos; `admin` gestiona usuarios).
2. Pantalla de administración de usuarios (hoy, desde la terminal).
3. Probar con Microsoft: usuario sin rol, cuenta desactivada, cambio de correo (debe seguir siendo el mismo usuario).
