' Starts the Lainframe voice bridge (bridge.ps1 next to this file) with no window. One copy only (the bridge exits if
' another is running). Normally you don't need this: LainBrain.bat (or "lain_brain.py run") starts the bridge and the
' watchers for you.
Set sh = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & here & "\bridge.ps1""", 0, False
