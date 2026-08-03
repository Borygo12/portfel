' Portfel — serwer danych dla aplikacji. Slucha takze w sieci lokalnej (--lan),
' zeby aplikacja na telefonie mogla sie polaczyc. Dostep z sieci wymaga tokenu.
' Nie otwiera przegladarki: interfejsem jest aplikacja, nie ten serwer.

Dim botDir, pyw, url, shell, killCmd, i
botDir = "C:\Users\Borys\Desktop\news-trader\bot"
pyw = "C:\Users\Borys\AppData\Local\Programs\Python\Python312\pythonw.exe"
url = "http://localhost:8500/"

Set shell = CreateObject("WScript.Shell")

' 1) UBIJ każdy działający panel (tylko procesy pythona — patrz komentarz w launch.vbs).
killCmd = "powershell -NoProfile -WindowStyle Hidden -Command """ & _
          "Get-CimInstance Win32_Process | " & _
          "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*dashboard.py*' } | " & _
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
shell.Run killCmd, 0, True

' 2) Poczekaj, aż port 8500 się zwolni (max ~6 s).
For i = 1 To 12
    If Not PortBusy(8500) Then Exit For
    WScript.Sleep 500
Next

' 3) Odpal świeży serwer w trybie sieciowym.
shell.CurrentDirectory = botDir
shell.Run """" & pyw & """ """ & botDir & "\dashboard.py"" --lan --no-browser", 0, False

Function PortBusy(port)
    Dim exec, out
    PortBusy = False
    On Error Resume Next
    Set exec = shell.Exec("cmd /c netstat -ano -p tcp | findstr LISTENING | findstr "":" & port & """")
    If Err.Number = 0 Then
        out = exec.StdOut.ReadAll()
        PortBusy = (InStr(out, ":" & port) > 0)
    End If
    On Error GoTo 0
End Function
