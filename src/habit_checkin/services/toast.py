"""Windows 系统通知（尽力而为）：通过 PowerShell 调用 Windows.UI.Notifications。

非打包应用未注册 AppUserModelID 时通知可能不显示，失败静默降级为仅 App 内提醒。
注意：不使用 -WindowStyle Hidden（该运行环境下会导致进程异常退出），改用 CREATE_NO_WINDOW。
"""
from __future__ import annotations

from habit_checkin.services.powershell import run_powershell_script

_PS1 = """
$ErrorActionPreference = 'SilentlyContinue'
$title = $args[0]
$message = $args[1]
$amp = [string][char]38
$lt = [string][char]60
$gt = [string][char]62
$t = $title.Replace($amp, $amp + 'amp').Replace($lt, $amp + 'lt').Replace($gt, $amp + 'gt')
$m = $message.Replace($amp, $amp + 'amp').Replace($lt, $amp + 'lt').Replace($gt, $amp + 'gt')
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>" + $t + "</text><text>" + $m + "</text></binding></visual></toast>")
    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('HabitCheckin.App')
    $notifier.Show($toast)
} catch {}
"""


def show_toast(title, message):
    """弹出 Windows 系统通知；成功返回 True，失败返回 False。"""
    try:
        proc = run_powershell_script(_PS1, title, message, timeout=10)
        return proc is not None and proc.returncode == 0
    except Exception:
        return False
