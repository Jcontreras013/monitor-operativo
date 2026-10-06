' ==============================================================================
' Lanza iniciar_sync_job.bat (robot de sincronizacion) SIN mostrar ventanas.
'
' Para que el robot arranque solo cada vez que se prende la PC o se inicia
' sesion en Windows:
'   1) Presiona Windows + R, escribe:  shell:startup   y da Enter.
'   2) Se abre una carpeta. Crea ahi un acceso directo a este archivo
'      (clic derecho sobre el archivo > Mostrar mas opciones > Crear acceso
'      directo, y mueve el acceso directo a esa carpeta).
'   3) Listo. Desde el proximo inicio de sesion el robot arranca solo y, si
'      se cae, iniciar_sync_job.bat lo vuelve a levantar.
'
' Para probarlo ahora mismo: doble clic a este archivo. Antes cierra el robot
' que este corriendo en una ventana de cmd, para no tener dos.
'
' Para PARAR el robot hay que cerrar los dos procesos (el .bat que lo
' relanza y el robot). En cmd como administrador:
'   powershell -c "Get-CimInstance Win32_Process | ? CommandLine -like '*sync_job*' | % { Stop-Process -Id $_.ProcessId -Force }"
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
carpeta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = carpeta
WshShell.Run """" & carpeta & "\iniciar_sync_job.bat" & """", 0, False
