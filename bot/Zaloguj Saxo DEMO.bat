@echo off
rem Ponowne logowanie do Saxo DEMO (SIM). Kliknij, gdy panel pokaze "Token Saxo wygasl".
rem Otworzy sie przegladarka — zaloguj sie do Saxo i zatwierdz dostep. Reszta dzieje sie sama.
title News Trader - logowanie Saxo DEMO
cd /d "%~dp0"
"C:\Users\Borys\AppData\Local\Programs\Python\Python312\python.exe" saxo_authorize.py sim
echo.
echo Gotowe. Mozesz zamknac to okno i odswiezyc panel.
pause
