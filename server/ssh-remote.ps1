# SSH vào board từ bất cứ đâu, qua Cloudflare tunnel (dịch vụ sshtunnel trên board).
#   .\ssh-remote.ps1                          # đang ở nhà: tự hỏi board hostname hiện tại
#   .\ssh-remote.ps1 abc-xyz.trycloudflare.com   # ở ngoài: lấy hostname ở trang web của board (Tổng quan)
# Cần: cloudflared (winget install --id Cloudflare.cloudflared) và khóa ~/.ssh/id_ed25519 đã thêm vào board.
param([string]$SshHost = "")

$ErrorActionPreference = "Stop"

$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    foreach ($p in "$PSScriptRoot\..\tools\cloudflared.exe", "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
                   "$env:ProgramFiles\cloudflared\cloudflared.exe") {
        if (Test-Path $p) { $cf = (Resolve-Path $p).Path; break }
    }
}
if (-not $cf) {
    Write-Host "Chua co cloudflared. Cai bang lenh:  winget install --id Cloudflare.cloudflared"
    exit 1
}

if (-not $SshHost) {
    foreach ($b in "192.168.2.1", "192.168.1.24") {
        try {
            $j = Invoke-RestMethod -TimeoutSec 3 "http://${b}:8080/api/public-url"
            if ($j.ssh) { $SshHost = $j.ssh; break }
        } catch {}
    }
    if (-not $SshHost) {
        Write-Host "Khong lay duoc hostname tu board. Mo trang web cua board (tab Tong quan) de xem, roi chay:"
        Write-Host "  .\ssh-remote.ps1 <hostname>.trycloudflare.com"
        exit 1
    }
}
$SshHost = $SshHost -replace '^https?://', '' -replace '/.*$', ''
Write-Host "SSH qua $SshHost ..."

# HostKeyAlias: hostname đổi liên tục nhưng khóa của board không đổi -> vẫn kiểm tra được đúng board.
ssh -o "ProxyCommand=`"$cf`" access ssh --hostname %h" -o HostKeyAlias=bpir3-remote `
    -o StrictHostKeyChecking=accept-new "root@$SshHost"
