' Jalankan run_once.bat tanpa menampilkan jendela (untuk Task Scheduler).
Set sh = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir
sh.Run "cmd /c """ & scriptDir & "\run_once.bat""", 0, False
