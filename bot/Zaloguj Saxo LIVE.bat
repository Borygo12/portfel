@echo off
rem Ponowne logowanie do Saxo LIVE (realne konto). Kliknij, gdy panel pokaze "Token Saxo wygasl".
rem Otworzy sie przegladarka — zaloguj sie do Saxo (kod SMS) i zatwierdz dostep. Reszta dzieje sie sama.
title News Trader - logowanie Saxo LIVE
cd /d "%~dp0"
"C:\Users\Borys\AppData\Local\Programs\Python\Python312\python.exe" saxo_authorize.py live
echo.
echo Gotowe. Mozesz zamknac to okno i odswiezyc panel.
pause
