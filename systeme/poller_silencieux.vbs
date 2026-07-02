' poller_silencieux.vbs — lance demarrer_poller.bat SANS fenetre visible.
' Utilise par la tache planifiee au logon : le poller "go" tourne en fond.
Set sh = CreateObject("WScript.Shell")
sh.Run """" & Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\")) & "demarrer_poller.bat""", 0, False
