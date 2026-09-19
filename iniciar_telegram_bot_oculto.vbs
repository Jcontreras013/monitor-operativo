' ==============================================================================
' Lanza iniciar_telegram_bot.bat SIN mostrar ninguna ventana de cmd.
'
' Para dejar el bot arrancando solo cada vez que se prende la PC o se inicia
' sesion en Windows (y no tener que acordarse de correrlo a mano):
'   1) Presiona Windows + R, escribe:  shell:startup   y da Enter.
'   2) Se abre una carpeta. Copia este archivo (iniciar_telegram_bot_oculto.vbs)
'      ahi dentro, o crea un acceso directo a el.
'   3) Listo. Desde el proximo inicio de sesion, el bot arranca solo, sin
'      ventanas visibles.
'
' Para probarlo ahora mismo sin reiniciar la PC: doble clic a este archivo.
'
' Para PARAR el bot: abre el Administrador de tareas (Ctrl+Shift+Esc), busca
' el proceso "Python" (o "py.exe" / "python.exe") y dale "Finalizar tarea".
' Si lo dejaste en la carpeta de inicio, se va a volver a levantar solo en el
' siguiente inicio de sesion.
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
carpeta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = carpeta
WshShell.Run """" & carpeta & "\iniciar_telegram_bot.bat" & """", 0, False
