@echo off
setlocal
set "CLAUDE=%USERPROFILE%\.local\bin\claude.exe"
title Claude Code - Login
echo ============================================================
echo   LOGIN do Claude Code (usa sua assinatura Claude)
echo ------------------------------------------------------------
echo   1) Vai ABRIR O NAVEGADOR. Entre com sua conta Claude.
echo   2) APROVE o acesso.
echo   3) Se pedir para COLAR UM CODIGO, copie do navegador e
echo      cole aqui na janela preta (botao direito = colar) + Enter.
echo ============================================================
echo.
"%CLAUDE%" setup-token
echo.
echo ============================================================
echo   Testando o login (deve aparecer LOGIN_OK)...
echo ============================================================
"%CLAUDE%" -p "responda apenas com: LOGIN_OK" < nul
echo.
echo ------------------------------------------------------------
echo   Se apareceu LOGIN_OK acima  -> pronto, pode fechar.
echo   Se apareceu "Not logged in" -> repita este arquivo.
echo ------------------------------------------------------------
pause
endlocal
