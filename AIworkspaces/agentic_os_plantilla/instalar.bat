@echo off
title Instalar Agentic OS
cd /d "%~dp0"
echo.
echo   Instalando skills, agentes y configuracion de Claude Code...
xcopy "_instalar\claude" ".claude" /E /I /Y >nul
if not exist ".mcp.json" copy "_instalar\mcp.json" ".mcp.json" >nul
echo   Listo. Skills y agentes instalados en .claude
echo.
pause
