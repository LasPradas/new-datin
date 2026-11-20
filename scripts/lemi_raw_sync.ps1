# =============================================================================
# LEMI-018 raw data sync → stageof-jayapura.bmkg.go.id (Stasiun Geofisika Jayapura)
#
# Runs every 15 minutes on the LEMI PC (172.21.63.105). Asks the server which raw files it
# already has (/magnet/api/lemi/raw/), then uploads every CLOSED local file from the last
# $DAYS days that is missing or larger locally. Missed days are caught up on the next run.
#
# The file lemi018.exe is writing is never opened: when another process opens it while LEMI
# writes its next second, lemi018.exe stops logging (watchdog restart, ~6 min lost; ~45 times
# 2-20 Nov 2026 from the old Copy-Item here, and also with FileShare ReadWrite). That file is
# the newest name; only the folder listing (name/size/time) is read for it.
# Its data so far is sent from the copy BMKG's upload.bat (task sync_mgnet, every 15 min) already
# makes with gawk in D:\DATABASE\yyyy\mm\raw\jayapura_lemi_raw_yyyymmdd.txt (gawk's read has not
# hung LEMI since 2023). The copy is sent under the active file's name when its first line matches
# that name; the real file replaces it on the server once LEMI closes it (00:00 UTC or restart).
# The server needs the first 4 hours of today to make yesterday's K index final.
#
# Server uses the files to compute the JYP K index itself (FMI method), so Jayapura
# does not depend on BMKG pusat for it. The rsync to BMKG pusat (upload.bat) is untouched.
#
# Setup (as Administrator):
#   1. Copy this file to C:\lemi_raw_sync\lemi_raw_sync.ps1
#   2. Put the LEMI_MONITOR_TOKEN (same as C:\LEMIMonitor) in C:\lemi_raw_sync\token.txt
#   3. schtasks /create /tn LEMIRawSync /sc minute /mo 15 /ru SYSTEM /rl HIGHEST /f ^
#        /tr "powershell -NoProfile -ExecutionPolicy Bypass -File C:\lemi_raw_sync\lemi_raw_sync.ps1"
# Manual check without uploading:  powershell -File lemi_raw_sync.ps1 -DryRun
# =============================================================================
param(
    [int]$Days = 30,
    [switch]$DryRun
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
$API_URL   = "https://stageof-jayapura.bmkg.go.id/magnet/api/lemi/raw/"
$RAW_DIR   = "D:\lemi018"
$DB_DIR    = "D:\DATABASE"   # upload.bat's copies (BMKG pusat rsync)
$TOKEN     = (Get-Content "$PSScriptRoot\token.txt" -Raw).Trim()
$LOG_FILE  = "$PSScriptRoot\lemi_raw_sync.log"
$CURL      = "$env:SystemRoot\System32\curl.exe"
# The public name goes through Cloudflare, which this LAN cannot reach: pin it to .189.
$RESOLVE   = "stageof-jayapura.bmkg.go.id:443:36.91.166.189"
# ─────────────────────────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss') $Message"
    Write-Host $line
    try { Add-Content -Path $LOG_FILE -Value $line -ErrorAction SilentlyContinue } catch {}
}

# Keep the log small: drop it when it passes 5 MB.
if ((Test-Path $LOG_FILE) -and ((Get-Item $LOG_FILE).Length -gt 5MB)) {
    Move-Item $LOG_FILE "$LOG_FILE.old" -Force
}

try {
    $manifestJson = & $CURL -s -f --max-time 60 --resolve $RESOLVE -H "Authorization: Bearer $TOKEN" "$($API_URL)?days=$($Days + 1)"
    if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
    $server = ($manifestJson | ConvertFrom-Json).files
} catch {
    Write-Log "ERROR: manifest not available: $_"
    exit 1
}

$since = (Get-Date).ToUniversalTime().Date.AddDays(-$Days)
$files = Get-ChildItem -Path $RAW_DIR -File -Filter "*.txt" | Where-Object {
    $_.Name -match '^\d{4} \d{2} \d{2} \d{2} \d{2} \d{2}\.txt$' -and
    [datetime]::ParseExact($_.Name.Substring(0, 10), 'yyyy MM dd', $null) -ge $since
} | Sort-Object Name

# Never touch the file LEMI is writing: the newest name, or anything written in the last minutes.
$all = Get-ChildItem -Path $RAW_DIR -File -Filter "*.txt" |
    Where-Object { $_.Name -match '^\d{4} \d{2} \d{2} \d{2} \d{2} \d{2}\.txt$' } | Sort-Object Name
$activeName = if ($all) { @($all)[-1].Name } else { $null }
$quietSince = (Get-Date).ToUniversalTime().AddMinutes(-3)

$sent = 0; $failed = 0; $skipped = 0; $open = 0
foreach ($f in $files) {
    if ($f.Name -eq $activeName -or $f.LastWriteTimeUtc -gt $quietSince) { $open++; continue }
    $remote = $server.PSObject.Properties[$f.Name]
    $remoteSize = if ($remote) { [int64]$remote.Value } else { -1 }
    if ($f.Length -le $remoteSize) { $skipped++; continue }

    if ($DryRun) {
        Write-Log "DRY-RUN would send $($f.Name) local=$($f.Length) server=$remoteSize"
        continue
    }
    # Copy first (closed file only, see above).
    $tmp = Join-Path $env:TEMP $f.Name
    try {
        Copy-Item -LiteralPath $f.FullName -Destination $tmp -Force
        $resp = & $CURL -s -f --max-time 300 --resolve $RESOLVE -H "Authorization: Bearer $TOKEN" -F "file=@$tmp" $API_URL
        if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
        Write-Log "OK   $($f.Name) $($f.Length) bytes $resp"
        $sent++
    } catch {
        Write-Log "ERR  $($f.Name): $_"
        $failed++
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

# The active file's data so far, from upload.bat's copy (never from LEMI's own file).
$partial = 'none'
if ($activeName -and -not $DryRun) {
    $base = $activeName.Substring(0, 19)                                  # "yyyy MM dd HH mm ss"
    $copy = Join-Path $DB_DIR ("{0}\{1}\raw\jayapura_lemi_raw_{0}{1}{2}.txt" -f `
        $base.Substring(0, 4), $base.Substring(5, 2), $base.Substring(8, 2))
    $remote = $server.PSObject.Properties[$activeName]
    $remoteSize = if ($remote) { [int64]$remote.Value } else { -1 }
    if (-not (Test-Path -LiteralPath $copy)) {
        $partial = 'no copy yet'
    } else {
        $c = Get-Item -LiteralPath $copy
        $first = Get-Content -LiteralPath $copy -TotalCount 1
        if ($c.LastWriteTimeUtc -gt (Get-Date).ToUniversalTime().AddMinutes(-1)) {
            $partial = 'copy being written'
        } elseif (-not $first -or -not $first.StartsWith($base)) {
            $partial = "copy is another file ($first)"
        } elseif ($c.Length -le $remoteSize) {
            $partial = 'up-to-date'
        } else {
            $tmp = Join-Path $env:TEMP $activeName
            try {
                Copy-Item -LiteralPath $copy -Destination $tmp -Force
                $resp = & $CURL -s -f --max-time 300 --resolve $RESOLVE -H "Authorization: Bearer $TOKEN" -F "file=@$tmp" $API_URL
                if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
                Write-Log "OK   $activeName (partial, from upload.bat copy) $($c.Length) bytes $resp"
                $partial = 'sent'
            } catch {
                Write-Log "ERR  $activeName partial: $_"
                $partial = 'failed'
            } finally {
                Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
Write-Log "Done: sent=$sent failed=$failed up-to-date=$skipped still-open=$open partial=$partial (last $Days days)"
if ($failed -gt 0 -or $partial -eq 'failed') { exit 2 }
