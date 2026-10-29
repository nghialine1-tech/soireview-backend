$nameserver = '203.119.73.106' # a.dns.vn authoritative server for .vn
$domains = @(
    'reviewshoop.vn',
    'reviewshoop.com.vn',
    'reviewshop.vn',
    'reviewshop.com.vn'
)

Write-Host "=== KIEM TRA TRUC TIEP TAI VNNIC ROOT DNS (.VN) ==="
foreach ($d in $domains) {
    try {
        $res = Resolve-DnsName -Name $d -Server $nameserver -Type ANY -ErrorAction Stop
        Write-Host "$d : ĐÃ ĐĂNG KÝ (Registered)" -ForegroundColor Red
    } catch {
        if ($_.Exception.Message -like "*DNS name does not exist*") {
            Write-Host "$d : CHƯA ĐĂNG KÝ (Available 100%)" -ForegroundColor Green
        } else {
            Write-Host "$d : CHƯA ĐĂNG KÝ ($($_.Exception.Message))" -ForegroundColor Cyan
        }
    }
}
