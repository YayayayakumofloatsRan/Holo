$procs = Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and (
    $_.CommandLine -like '*wechat_helper.py*watch-live*' -or
    $_.CommandLine -like '*wechat_helper.py*watch-pyweixin*' -or
    $_.CommandLine -like '*wechat_helper.py*watch-wcf*' -or
    $_.CommandLine -like '*pyweixin_watcher.pyw*' -or
    $_.CommandLine -like '*weixin_sender.pyw*'
  )
}

foreach ($proc in $procs) {
  Stop-Process -Id $proc.ProcessId -Force
}

$procs | Select-Object ProcessId, CommandLine | ConvertTo-Json -Depth 3
