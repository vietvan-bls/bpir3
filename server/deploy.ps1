# Copy server từ máy tính lên board rồi khởi động lại dịch vụ.
# Chạy trong PowerShell (trong thư mục D:\bpir3\server):
#   .\deploy.ps1                       # khi máy tính cắm LAN / bắt Wi-Fi BPI-R3
#   .\deploy.ps1 -Board 192.168.1.24   # khi máy tính ở mạng VQH
#   .\deploy.ps1 -SshTunnel            # bật thêm SSH từ xa qua Cloudflare (sshtunnel.init)
param([string]$Board = "192.168.2.1", [switch]$SshTunnel)

$ErrorActionPreference = "Stop"
$opt = @("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR")
$dst = "root@$Board"

# Init script phải dùng xuống dòng kiểu Linux (LF) và UTF-8 không BOM, nên tạo bản tạm.
function Convert-ToLF([string]$name) {
    $out = Join-Path $env:TEMP $name
    $text = (Get-Content -Raw -Encoding UTF8 "$PSScriptRoot\$name") -replace "`r`n", "`n"
    [IO.File]::WriteAllText($out, $text, (New-Object Text.UTF8Encoding $false))
    return $out
}

# Board vào bằng khóa ~/.ssh/id_ed25519 (root có mật khẩu). BatchMode: thiếu khóa thì báo lỗi, không treo hỏi mật khẩu.
ssh @opt -o BatchMode=yes $dst "mkdir -p /root/server"
if ($LASTEXITCODE) { throw "Khong SSH duoc bang khoa. Them khoa: type `$env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@$Board `"cat >> /etc/dropbear/authorized_keys`"" }
foreach ($f in "app.py", "vision.py", "traffic.py", "music.py", "speaker.py", "iot.py", "kho.py", "vpn.py", "index.html", "iot.html", "kho.html") {
    scp @opt "$PSScriptRoot\$f" "${dst}:/root/server/"
    if ($LASTEXITCODE) { throw "Copy $f failed" }
}
scp @opt (Convert-ToLF "myserver.init") "${dst}:/etc/init.d/myserver"
scp @opt (Convert-ToLF "cftunnel.init") "${dst}:/etc/init.d/cftunnel"
ssh @opt $dst "chmod +x /etc/init.d/myserver /etc/init.d/cftunnel; service myserver enable; service myserver restart; sleep 1; logread -e python3 | tail -3"

# Tunnel Cloudflare: chỉ bật nếu chưa chạy, để link không bị đổi mỗi lần deploy.
ssh @opt $dst "service cftunnel enable; pgrep -f 'url http://127.0.0.1:8080' >/dev/null || { service cftunnel start; sleep 8; }; echo Link cong khai: `$(service cftunnel url)"

if ($SshTunnel) {
    # SSH từ xa: dropbear thứ hai chỉ nghe 127.0.0.1:2222, chỉ cho đăng nhập bằng khóa; tunnel trỏ vào đó.
    scp @opt (Convert-ToLF "sshtunnel.init") "${dst}:/etc/init.d/sshtunnel"
    ssh @opt $dst ("chmod +x /etc/init.d/sshtunnel; " +
        "uci -q get dropbear.remote >/dev/null || { uci set dropbear.remote=dropbear; " +
        "uci set dropbear.remote.Interface=loopback; uci set dropbear.remote.Port=2222; " +
        "uci set dropbear.remote.PasswordAuth=off; uci set dropbear.remote.RootPasswordAuth=off; " +
        "uci commit dropbear; (sleep 1; service dropbear restart) >/dev/null 2>&1 </dev/null & }")
    Start-Sleep 4   # dropbear khởi động lại (cắt phiên SSH này nếu chạy thẳng, nên cho chạy nền)
    ssh @opt $dst "service sshtunnel enable; pgrep -f 'url ssh://' >/dev/null || { service sshtunnel start; sleep 8; }; echo SSH tu xa: `$(service sshtunnel url)"
}
Write-Host "Xong. Trong mang: http://${Board}:8080"
