param([string]$cmd = "", [int]$wait = 5)
$p = New-Object System.IO.Ports.SerialPort COM8,460800,None,8,One
$p.ReadTimeout = 500
$p.Open()
Start-Sleep -Milliseconds 400
$p.DiscardInBuffer()
$p.WriteLine($cmd)
Start-Sleep -Seconds $wait
$out = $p.ReadExisting()
$p.Close()
if ([string]::IsNullOrWhiteSpace($out)) { Write-Host "(no output)" } else { Write-Host $out }
