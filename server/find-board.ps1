# In ra IP của board BPI-R3 (máy đầu tiên trả lời /api/whoami ở cổng 8080).
# Thử: gateway của máy tính (thường chính là board khi bắt Wi-Fi BPI-R3) -> IP quen -> IP board bên mạng nhà.
$candidates = @()
$candidates += Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
    ForEach-Object { $_.IPv4DefaultGateway.NextHop }
$candidates += '192.168.2.1', '192.168.1.24'

foreach ($ip in ($candidates | Select-Object -Unique)) {
    $c = New-Object Net.Sockets.TcpClient
    try {
        if (-not ($c.ConnectAsync($ip, 8080).Wait(800) -and $c.Connected)) { continue }
    } catch { continue } finally { $c.Close() }
    try {
        $r = Invoke-WebRequest -UseBasicParsing "http://${ip}:8080/api/whoami" -TimeoutSec 3
        if ($r.Content -match '"local"') { $ip; exit 0 }
    } catch {}
}
exit 1
