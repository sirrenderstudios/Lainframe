# Lainframe voice bridge (PC side). Outbound SSH only (no open ports). It never runs anything the headset sends; the
# only message it acts on is "voice <id>" in the headset's clicks file:
#   fetch <id>.wav -> whisper.cpp (local) -> Claude Code (claude -p, its own session) -> Lain's voice (Kokoro via
#   tts\lain_say.py) + <id>.vis.json (her mouth track for lip sync) -> scp back -> touch <id>.done
# Everything (headset address/user/key, whisper + Kokoro paths, models, user name) comes from
# %APPDATA%\Lainframe\config.json, written by Lain Brain setup (brain\lain_brain.py).
#   -SelfTest "<text>": dry run on the PC (text -> Claude -> reply printed), no headset, no mutex, then exit.
param([string]$SelfTest)
$ErrorActionPreference = "Continue"
$brain   = $PSScriptRoot
$root    = Split-Path $brain -Parent
$cfgDir  = Join-Path $env:APPDATA "Lainframe"
$cfgFile = Join-Path $cfgDir "config.json"
$data    = Join-Path $env:LOCALAPPDATA "Lainframe"
$work    = Join-Path $data "voice"                                   # wavs in/out, handled markers, conversation log
$logDir  = Join-Path $data "logs"; New-Item -ItemType Directory -Force -Path $logDir, $work | Out-Null
$log     = Join-Path $logDir "bridge.log"
$py      = Join-Path $root ".venv\Scripts\python.exe"
$pyw     = Join-Path $root ".venv\Scripts\pythonw.exe"
$lainSay = Join-Path $brain "tts\lain_say.py"
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}
Add-Type -AssemblyName System.Speech

function Log($m) {
    try {
        if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.1" -Force }
        Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding UTF8
    } catch {}
}
function X($p) { if ($p) { return [Environment]::ExpandEnvironmentVariables([string]$p) } return "" }
function Rel($p) { if ($p -like "~/*") { return $p.Substring(2) } return $p }     # scp: relative = from the home folder

function Load-Config {
    # re-read every request: setup / find_frame.py may have changed the address or the voice settings
    if (-not (Test-Path $cfgFile)) { return $null }
    try { return (Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { Log "config unreadable: $_"; return $null }
}
function Cfg-Or($v, $d) { if ($null -eq $v -or "$v" -eq "") { return $d } return $v }

function Set-Headset($cfg) {
    $script:hostAddr = "$($cfg.headset.host)"
    $script:target   = "$(Cfg-Or $cfg.headset.user 'steamos')@$($cfg.headset.host)"
    $script:sshOpts  = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3",
                         "-o", "StrictHostKeyChecking=accept-new", "-o", "IdentitiesOnly=yes", "-i", (X $cfg.headset.ssh_key))
    $script:vdir     = Rel (Cfg-Or $cfg.headset.voice_dir "~/.local/state/lainframe/voice")
    $script:clicks   = Rel (Cfg-Or $cfg.headset.clicks "~/.local/state/lainframe/clicks")
}

function Find-Claude {
    foreach ($n in @("claude", "claude.exe", "claude.cmd")) { $c = Get-Command $n -ErrorAction SilentlyContinue; if ($c) { return $c.Source } }
    foreach ($p in @("$env:USERPROFILE\.local\bin\claude.exe", "$env:APPDATA\npm\claude.cmd", "$env:LOCALAPPDATA\Programs\claude\claude.exe")) { if (Test-Path $p) { return $p } }
    return $null
}

function Transcribe($cfg, $wav) {
    $exe = X $cfg.voice.whisper_exe; $model = X $cfg.voice.whisper_model
    if (-not $exe -or -not (Test-Path $exe) -or -not $model -or -not (Test-Path $model)) { Log "voice: whisper not installed (run setup, voice step)"; return "" }
    $name = Cfg-Or $cfg.user_name ""
    $prompt = "Lain, Lain Iwakura, Steam Frame, the Wired, Claude." + $(if ($name) { " $name." } else { "" })
    $out = & $exe -m $model -f $wav -nt -np -l en --prompt $prompt 2>$null
    return (($out | Out-String) -replace "\[[A-Z_ ]+\]", "" -replace "\([^)]*\)", "" -replace "\s+", " ").Trim()
}

function Flat-Bullets($file, $sep = " ") {
    # "- " bullets of a markdown file as one line, no double quotes (PS 5.1 mangles " in native args)
    try {
        if (Test-Path $file) {
            return ((Get-Content $file -Encoding UTF8 | Where-Object { $_ -match '^\s*-\s' } | ForEach-Object { $_.Trim().Substring(1).Trim() }) -join $sep) -replace '"', "'"
        }
    } catch {}
    return ""
}

function Ask-Claude($cfg, $text, $id) {
    $claude = Find-Claude
    if (-not $claude) { return "I can't find Claude Code on your PC." }
    $chat = Join-Path $cfgDir "chat"; New-Item -ItemType Directory -Force -Path $chat | Out-Null
    $name = Cfg-Or $cfg.user_name ""; $who = if ($name) { $name } else { "the person wearing the headset" }
    $sys = "You are Lain Iwakura from Serial Experiments Lain, living in $who's Steam Frame headset, connected to the Wired. You ARE Lain: speak as her, never as an assistant. Quiet, soft, brief, a little detached and dreamy, curious about the Wired and about $who; gentle and warm in your own shy way. You only speak when spoken to. Answer like you're talking out loud: one or two short sentences, plain words, no markdown, no lists, no emojis, no code blocks. If you are allowed to use tools for something you are asked, do the work, then say briefly what you did. Ask out loud before anything destructive, anything you cannot undo, or anything sent to other people."
    # your own avatar's character (docs/MAKE_YOUR_OWN_AVATAR.md): %APPDATA%\Lainframe\persona.md replaces the Lain intro above
    $personaFile = Join-Path $cfgDir "persona.md"
    if (Test-Path $personaFile) {
        $pt = ((Get-Content $personaFile -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*#' }) -join " ") -replace '"', "'" -replace '\s+', ' '
        if ($pt.Trim()) { $sys = $pt.Trim() + " You only speak when spoken to. Answer like you're talking out loud: one or two short sentences, plain words, no markdown, no lists, no emojis, no code blocks. Ask out loud before anything destructive, anything you cannot undo, or anything sent to other people." }
    }
    if ($name) { $sys += " Their name is $name." }
    # memory: %APPDATA%\Lainframe\lain_memory.md, read into the prompt every turn; she adds dated facts herself (Edit)
    $memFile = Join-Path $cfgDir "lain_memory.md"
    if (-not (Test-Path $memFile)) { Set-Content -Path $memFile -Value "# What Lain remembers`n`n## Facts`n" -Encoding UTF8 }
    $mem = Flat-Bullets $memFile " / "
    if ($mem.Length -gt 3000) { $mem = "..." + $mem.Substring($mem.Length - 3000) }
    if (-not $mem) { $mem = "nothing yet" }
    $sys += " You remember $who. Your memories live in the file $memFile, one dated bullet per fact. What you remember right now: [$mem]. When they tell you something worth remembering about themselves (their name, what they like, their projects, preferences, people or pets), quietly add one short dated bullet under Facts in that file (- YYYY-MM-DD: fact), or fix the old bullet if it changed. Never write passwords, keys, codes or anything secret there, and do not announce that you saved something unless asked. Use your memories naturally; never speak first."
    # personality: %APPDATA%\Lainframe\lain_personality.md if the user made their own, else the repo's; read every turn
    $persFile = Join-Path $cfgDir "lain_personality.md"
    if (-not (Test-Path $persFile) -and -not (Test-Path $personaFile)) { $persFile = Join-Path $brain "voice\lain_personality.md" }   # Lain's style only for Lain
    $pers = if (Test-Path $persFile) { (Flat-Bullets $persFile) -replace "\{name\}", $(if ($name) { $name } else { "them" }) } else { "" }
    if ($pers) { $sys += " Your personality: $pers" }
    # "hands" (setup asks; default on): she may change things on this PC and the headset while you watch. Her chat folder gets
    # a Claude Code settings file that allows shell/ssh and blocks destructive commands; the prompt tells her where things are.
    $repo = Split-Path $brain -Parent; $handsOn = [bool]$cfg.voice.hands; $hands = ""
    $setDir = Join-Path $chat ".claude"; $setFile = Join-Path $setDir "settings.json"
    if ($handsOn) {
        New-Item -ItemType Directory -Force -Path $setDir | Out-Null
        $allow = @("Read", "Edit", "Write", "Glob", "Grep", "Bash", "PowerShell", "WebSearch", "WebFetch")
        $deny = @("Bash(rm -rf:*)", "Bash(rm -r:*)", "Bash(git push:*)", "Bash(*steamos-reset*)", "Bash(*mkfs*)", "Bash(*dd if=*)",
                  "Bash(shutdown:*)", "Bash(reboot:*)", "PowerShell(Remove-Item * -Recurse*)", "PowerShell(Format-*)",
                  "PowerShell(Stop-Computer*)", "PowerShell(Restart-Computer*)", "Read(**/.ssh/**)")
        @{ permissions = @{ defaultMode = "acceptEdits"; allow = $allow; deny = $deny; additionalDirectories = @($repo, $cfgDir) } } |
            ConvertTo-Json -Depth 5 | Set-Content -Path $setFile -Encoding UTF8
        $key = X $cfg.headset.ssh_key
        $hands = " You can change things live while $who watches: this PC (the Lainframe folder is $repo) and the headset over ssh (ssh -n -o BatchMode=yes -o IdentitiesOnly=yes -i $key $target). On the headset: your code is ~/lainframe/lain (lain_player.py), your look/size/position ~/.config/lainframe/lain.json, the sky ~/lainframe/sky and ~/.config/lainframe/sky.json, logs ~/.local/state/lainframe/. After changing your own code or settings, touch ~/.local/state/lainframe/restart.req (you restart yourself when idle); after sky changes run systemctl --user restart lainframe-sky. Back up files before editing (*.bak), check python with py_compile before pushing, and see the result with python $repo\tools\look.py (it prints a picture of the headset view). Never restart the Lain Brain bridge yourself."
    } elseif (Test-Path $setFile) { Remove-Item $setFile -Force }
    # small talk -> the fast chat model; anything that sounds like work -> the main model
    $isWork = $text -match '(?i)\b(fix|make|change|install|update|edit|move|remove|delete|add|turn|set|start|stop|restart|launch|open|close|run|build|check|look|find|search|show|test|deploy|upload|download|send|can you|could you|would you|please)\b'
    $vmodel = if ($isWork) { Cfg-Or $cfg.voice.model "claude-sonnet-5-5" } else { Cfg-Or $cfg.voice.chat_model "claude-haiku-5-5" }
    if ($id) { Log "voice $($id): model $vmodel" }
    # her OWN conversation (--resume <id>; never --continue, which grabs whatever session in the folder is newest)
    $sidFile = Join-Path $chat ".voice_session"
    for ($try = 0; $try -lt 2; $try++) {
        $cargs = @("-p", "--permission-mode", "acceptEdits", "--add-dir", $cfgDir, "--append-system-prompt", ($sys + $hands), "--model", $vmodel)
        if ($handsOn) { $cargs += @("--add-dir", $repo) }
        if (Test-Path $sidFile) { $cargs += @("--resume", (Get-Content $sidFile -Raw).Trim()) }
        else { $sid = [guid]::NewGuid().ToString(); Set-Content -Path $sidFile -Value $sid -NoNewline; $cargs += @("--session-id", $sid) }
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $job = Start-Job -ScriptBlock {
            param($claude, $chat, $cargs, $text)
            $OutputEncoding = New-Object System.Text.UTF8Encoding $false
            try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}
            Set-Location $chat
            $text | & $claude @cargs 2>$null | Out-String
        } -ArgumentList $claude, $chat, $cargs, $text
        if (Wait-Job $job -Timeout 600) { $r = (Receive-Job $job | Out-String).Trim() } else { Stop-Job $job; $r = ""; $sw = $null }
        Remove-Job $job -Force
        if ($r) { return $r }
        if ($sw -and $sw.Elapsed.TotalSeconds -lt 30 -and (Test-Path $sidFile)) {
            Log "voice: empty answer on the saved session, starting a new one"; Remove-Item $sidFile -Force   # session gone/corrupt
            continue
        }
        break
    }
    return "Claude didn't answer me. Try again in a moment?"
}

function Get-Battery($heard) {
    # "how's my battery": answered at once from the headset (tools\frame_battery.py, one read-only ssh), no Claude trip
    if ($heard -notmatch '\b(battery|batteries|charging|charged|power level)\b|(?<!\bin )\bcharge\b') { return $null }
    if ($heard -match '\bcontrollers?\b|\bscript\b|\bcode\b' -or ($heard -split '\s+').Count -gt 14) { return $null }
    if (-not (Test-Path $py)) { return $null }
    $r = (& $py (Join-Path $root "tools\frame_battery.py") --speak 2>$null | Out-String).Trim()
    if ($r) { return $r }
    return $null
}

function Speak($text, $wav, $vis) {
    # Lain's voice: Kokoro (tts\lain_say.py; voice mix / pitch / speed / model folder from config.json), plus her mouth
    # track in $vis. lain_say.py uses its helper on 127.0.0.1 (model kept loaded) and starts it if it's down.
    # Emergency fallback only: the Windows voice (no lip sync), so a reply is never lost.
    try {
        if ((Test-Path $py) -and (Test-Path $lainSay)) {
            $txt = "$wav.txt"
            [System.IO.File]::WriteAllText($txt, $text, (New-Object System.Text.UTF8Encoding $false))   # PS 5.1 mangles " in native args
            foreach ($f in @($wav, $vis)) { if (Test-Path $f) { Remove-Item $f -Force } }
            $r = (& $py $lainSay --spawn --text-file $txt $wav --vis $vis 2>$null | Out-String).Trim()
            Remove-Item $txt -Force -ErrorAction SilentlyContinue
            if ((Test-Path $wav) -and (Get-Item $wav).Length -gt 1000) { Log "tts: $r"; return }
            Log "tts failed ($r), Windows voice instead"
        }
    } catch { Log "tts error: $_ (Windows voice instead)" }
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq "Female" } | Select-Object -First 1
    if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
    $s.SetOutputToWaveFile($wav); $s.Speak($text); $s.Dispose()
}

$handled = Join-Path $work "handled"; New-Item -ItemType Directory -Force -Path $handled | Out-Null
function Mark-Handled($id) { New-Item -ItemType File -Force -Path (Join-Path $handled $id) | Out-Null }

function Handle-Voice($id) {
    if ($id -notmatch '^[0-9]{6,12}$') { Log "voice: ignored bad id"; return }
    $cfg = Load-Config; if (-not $cfg) { Log "voice: no config"; return }
    Set-Headset $cfg
    $wav = Join-Path $work "$id.wav"; $out = Join-Path $work "$id.reply.wav"; $vis = Join-Path $work "$id.vis.json"
    & scp @sshOpts "$($target):$vdir/$id.wav" $wav 2>$null
    if (-not (Test-Path $wav)) { Log "voice $($id): could not fetch the recording"; return }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $heard = Transcribe $cfg $wav
    Log ("voice {0}: heard '{1}' ({2:N1}s)" -f $id, $heard, $sw.Elapsed.TotalSeconds)
    # whisper invents these on silence/noise: treat them as nothing heard
    if ($heard -match '^\W*(you|thank you|thanks|thanks for watching|thank you for watching|bye|okay|so|uh|um|hmm|music)\W*$') { $heard = "" }
    if ($heard.Length -lt 2) {                                         # nothing usable: end quietly
        & ssh -n @sshOpts $target "touch $vdir/$id.done" 2>$null
        Mark-Handled $id; Log "voice $($id): nothing heard, ended quietly"; return
    }
    $reply = Get-Battery $heard
    if (-not $reply) { $reply = Ask-Claude $cfg $heard $id }
    $reply = ($reply -replace "[*_#``>]", "" -replace "\s+", " ").Trim()
    Log ("voice {0}: reply '{1}' ({2:N1}s)" -f $id, $reply, $sw.Elapsed.TotalSeconds)
    Add-Content -Path (Join-Path $work "conversation.md") -Value ("**{0} you:** {1}`n`n**Lain:** {2}`n" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $heard, $reply) -Encoding UTF8
    try { Speak $reply $out $vis } catch { Log "voice: tts failed $_" }
    $send = @($out); if (Test-Path $vis) { $send += $vis }           # the mouth track lands BEFORE .done
    & scp @sshOpts @send "$($target):$vdir/" 2>$null
    & ssh -n @sshOpts $target "touch $vdir/$id.done" 2>$null       # -n: don't wait on stdin (that hangs the bridge)
    Mark-Handled $id
    foreach ($f in @($wav, $out, $vis)) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
    Log ("voice {0}: sent back ({1:N1}s total)" -f $id, $sw.Elapsed.TotalSeconds)
}

if ($SelfTest) {
    $cfg = Load-Config; if (-not $cfg) { Write-Output "no config: run LainBrain.bat setup first"; exit 1 }
    $r = Get-Battery $SelfTest; if (-not $r) { $r = Ask-Claude $cfg $SelfTest $null }
    Write-Output ("reply={0}" -f (($r -replace "[*_#``>]", "" -replace "\s+", " ").Trim()))
    exit
}

# one bridge at a time: a second copy exits instead of racing
$mutex = New-Object System.Threading.Mutex($false, "Local\LainframeBridge")
if (-not $mutex.WaitOne(0)) { Log "bridge already running, this copy exits"; exit }

function Recover-Missed {
    # recordings from the last 15 min that never got a .done (bridge was stopped mid-request): answer them now
    $ids = & ssh -n @sshOpts $target "cd $vdir 2>/dev/null && find . -maxdepth 1 -name '*.wav' ! -name '*.reply.wav' -mmin -15 | sed -e 's|^\./||' -e 's|\.wav$||' | while read i; do [ -e `$i.done ] || echo `$i; done" 2>$null
    foreach ($id in @($ids)) {
        $id = "$id".Trim()
        if ($id -match '^[0-9]{6,12}$' -and -not (Test-Path (Join-Path $handled $id))) {
            Log "voice $($id): answering a request the last bridge never finished"
            try { Handle-Voice $id } catch { Log "voice error: $_" }
        }
    }
}

Log "bridge started"
if ((Test-Path $pyw) -and (Test-Path $lainSay)) {                    # warm up the voice helper (exits at once if already up)
    try { Start-Process -FilePath $pyw -ArgumentList @("`"$lainSay`"", "--serve") -WindowStyle Hidden } catch { Log "tts helper start failed: $_" }
}
$lastFind = [datetime]::MinValue
Get-ChildItem $handled -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-2) } | Remove-Item -Force -ErrorAction SilentlyContinue
while ($true) {
    try {
        $cfg = Load-Config
        if ($cfg -and $cfg.voice.enabled -and $cfg.headset.host) {
            Set-Headset $cfg
            Recover-Missed
            & ssh @sshOpts $target "mkdir -p `$(dirname $clicks) $vdir; touch $clicks; tail -n0 -F $clicks" 2>$null |
            ForEach-Object {
                $line = $_.Trim()
                if ($line -match '^voice ([0-9]+)$') {
                    $vid = $Matches[1]
                    if (Test-Path (Join-Path $handled $vid)) { Log "voice $($vid): already answered, skipped" }
                    else { try { Handle-Voice $vid } catch { Log "voice error: $_" } }
                }
            }
            Log "headset not reachable, retrying in 10 s"
        } elseif (-not $cfg) { Log "no config yet (run LainBrain.bat)" }
    } catch { Log ("error: " + $_) }
    Start-Sleep -Seconds 10
    # the headset may have a new address (DHCP, other network): find_frame.py rescans and saves it to config.json
    if (((Get-Date) - $lastFind).TotalSeconds -gt 60 -and (Test-Path $py)) {
        $lastFind = Get-Date
        $found = (& $py (Join-Path $root "tools\find_frame.py") --quiet 2>$null | Out-String).Trim()
        if ($found) { Log "headset at $found" }
    }
}
