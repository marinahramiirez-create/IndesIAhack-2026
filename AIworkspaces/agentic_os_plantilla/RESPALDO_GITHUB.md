# Respaldo en GitHub (privado)

Con esto tu OS queda con copia de seguridad, historial de cambios y acceso desde Claude Code en la web o el móvil. Lo haces una sola vez y toma unos 10 minutos.

## Paso a paso con GitHub Desktop (la forma más fácil)

1. Crea una cuenta en github.com si aún no tienes una.
2. Descarga e instala GitHub Desktop (desktop.github.com) e inicia sesión.
3. En GitHub Desktop ve a **File, Add local repository** y elige la carpeta de tu OS.
4. Como todavía no es un repositorio, te ofrecerá **create a repository**. Acéptalo.
5. Pulsa **Publish repository** y deja marcada la casilla **Keep this code private**. Es importante que sea privado porque contendrá tu contexto personal.
6. Cada vez que quieras guardar una versión, escribe un resumen corto y pulsa **Commit** y luego **Push origin**.

## Consejo: sube y baja a menudo

Si usas el OS desde varios sitios (tu PC y tareas programadas en la nube), sube tus cambios al terminar cada sesión y trae los de GitHub (**Fetch** y **Pull**) antes de empezar. Así evitas tener dos versiones distintas del mismo archivo.

## Para que sea automático (opcional)

En Obsidian instala el plugin comunitario **Git**. Puede hacer commit y push automáticos cada cierto tiempo.

## Qué no se sube

El archivo `.gitignore` ya excluye la papelera, el estado temporal de Obsidian y la configuración local de Claude Code. Aun así, nunca guardes contraseñas, números de cuenta ni documentos de identidad en esta carpeta.
