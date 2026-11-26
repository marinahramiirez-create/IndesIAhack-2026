@echo off
title Agentic OS Dashboard
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo   No encuentro Node.js en este equipo.
  echo   Instalalo desde https://nodejs.org ^(version LTS^) y vuelve a abrir este archivo.
  echo.
  pause
  exit /b 1
)
if not exist ".claude\skills\briefing\SKILL.md" (
  xcopy "_instalar\claude" ".claude" /E /I /Y >nul
  if not exist ".mcp.json" copy "_instalar\mcp.json" ".mcp.json" >nul
)
start "" http://localhost:4747
node dashboard\server.js
pause
