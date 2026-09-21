$pids = Get-NetTCPConnection -LocalPort 9100 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $pids) { Stop-Process -Id $procId -Force; Write-Output "killed $procId" }
if (-not $pids) { Write-Output "no-listener" }
