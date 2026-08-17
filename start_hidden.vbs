Set ws = CreateObject("WScript.Shell")
Set env = ws.Environment("PROCESS")

py = env("HABIT_PY")
root = env("HABIT_ROOT")
if py = "" or root = "" then
    MsgBox "HABIT_PY or HABIT_ROOT is not set.", 16, "习惯打卡"
    WScript.Quit 1
end if

env("PYTHONPATH") = root & "\src"
ws.CurrentDirectory = root
ws.Run """" & py & """ -m habit_checkin", 0, False
