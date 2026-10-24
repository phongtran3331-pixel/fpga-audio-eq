$p = New-Object System.IO.Ports.SerialPort COM8,460800,None,8,One
$p.Open()
Start-Sleep -Milliseconds 300
$p.Write([char]3)
Start-Sleep -Seconds 1
$p.WriteLine('')
Start-Sleep -Seconds 2
$out = $p.ReadExisting()
$p.Close()
Write-Host $out
