param([string]$cmd, [int]$baud = 115200, [int]$wait = 10)
$p = New-Object System.IO.Ports.SerialPort COM8,$baud,None,8,One
$p.ReadTimeout = 1000
try {
    $p.Open()
    Start-Sleep -Milliseconds 500
    $null = $p.ReadExisting()
    $p.Write($cmd + "`r")
    $acc = ''
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $wait) {
        Start-Sleep -Milliseconds 500
        $acc += $p.ReadExisting()
        if ($acc -match 'xilinx@pynq:~\$\s*$') { break }
    }
    Write-Output $acc
} finally {
    $p.Close()
}
