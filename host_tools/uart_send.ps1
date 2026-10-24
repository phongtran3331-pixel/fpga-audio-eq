# uart_send.ps1 - send a file to the PYNQ board over serial, base64 chunked, MD5 verified
param(
  [string]$file = "",
  [string]$remote = "",
  [string]$md5 = "",
  [int]$start = 0,
  [int]$end = -1,
  [switch]$boost,
  [switch]$restore
)

if ($boost) {
  $p = New-Object System.IO.Ports.SerialPort COM8,115200,None,8,One
  $p.Open(); Start-Sleep -Milliseconds 400
  $p.WriteLine('stty -F /dev/ttyPS0 460800')
  Start-Sleep -Seconds 1
  $p.Close()
  Write-Host "BOOSTED_TO_460800"
  exit 0
}
if ($restore) {
  $p = New-Object System.IO.Ports.SerialPort COM8,460800,None,8,One
  $p.Open(); Start-Sleep -Milliseconds 400
  $p.WriteLine('stty -F /dev/ttyPS0 115200')
  Start-Sleep -Seconds 1
  $p.Close()
  Write-Host "RESTORED_TO_115200"
  exit 0
}

$port = New-Object System.IO.Ports.SerialPort COM8,460800,None,8,One
$port.ReadTimeout = 300
$port.Open()
Start-Sleep -Milliseconds 500
$port.DiscardInBuffer()

function Wait-Prompt([int]$timeoutSec) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $acc = ""
  while ($sw.Elapsed.TotalSeconds -lt $timeoutSec) {
    Start-Sleep -Milliseconds 20
    $acc += $port.ReadExisting()
    if ($acc -match 'xilinx\@pynq:~\$\s*$') { return $acc }
  }
  throw "prompt timeout"
}
function Send-Cmd([string]$line, [int]$t) {
  $port.WriteLine($line)
  return (Wait-Prompt $t)
}

$port.WriteLine("")
Wait-Prompt 5 | Out-Null

if ($start -eq 0) { Send-Cmd 'rm -f /tmp/x.b64' 5 | Out-Null }

$bytes = [System.IO.File]::ReadAllBytes($file)
$b64 = [Convert]::ToBase64String($bytes)
$chunks = [Math]::Ceiling($b64.Length / 2000)
if ($end -lt 0 -or $end -ge $chunks) { $end = $chunks - 1 }

for ($i = $start; $i -le $end; $i++) {
  $off = $i * 2000
  $len = [Math]::Min(2000, $b64.Length - $off)
  $piece = $b64.Substring($off, $len)
  try {
    Send-Cmd ("printf '%s' '" + $piece + "' >> /tmp/x.b64") 8 | Out-Null
  } catch {
    Write-Host ("RETRY chunk " + $i)
    Send-Cmd ("printf '%s' '" + $piece + "' >> /tmp/x.b64") 10 | Out-Null
  }
  if (($i % 200) -eq 0) { Write-Host ("chunk " + $i + "/" + $end) }
}

if ($end -eq $chunks - 1) {
  Send-Cmd ('base64 -d /tmp/x.b64 > ' + $remote) 120 | Out-Null
  $m = Send-Cmd ('md5sum ' + $remote) 30
  Write-Host $m
  if ($m -match $md5) { Write-Host "MD5_MATCH_OK" } else { Write-Host "MD5_MISMATCH_FAIL" }
} else {
  Write-Host ("PARTIAL_DONE up to chunk " + $end)
}
$port.Close()
