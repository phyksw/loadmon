# Shared persistence and bounded default-mailbox discovery. No Outlook connection at import.
function Get-CollectionPython([string]$Root) {
    if ($script:outlookPythonExe -and (Test-Path -LiteralPath $script:outlookPythonExe -PathType Leaf)) {
        return $script:outlookPythonExe
    }
    # run.py passes its verified interpreter. Standalone collectors also support
    # the same embedded / PATH / py -3 launch modes as LoadMonitor25.bat.
    $candidates = New-Object 'System.Collections.Generic.List[object]'
    if ($env:LM_PYTHON_EXE) { $candidates.Add(@{ exe = $env:LM_PYTHON_EXE; prefix = @() }) }
    $candidates.Add(@{ exe = (Join-Path $Root 'python\python.exe'); prefix = @() })
    foreach ($name in @('python', 'py')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if ($command) { $candidates.Add(@{ exe = $command.Source; prefix = $(if ($name -eq 'py') { @('-3') } else { @() }) }) }
    }
    foreach ($candidate in $candidates) {
        $exe = [string]$candidate.exe
        # Windows' Store shortcut is not an installed runtime and may open a UI.
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf) -or [IO.Path]::GetExtension($exe).ToLowerInvariant() -notin @('.exe', '.com', '.cmd', '.bat') -or
            $exe -match '\\Microsoft\\WindowsApps\\python(?:3)?\.exe$') { continue }
        try {
            $prefix = @($candidate.prefix)
            $result = @(& $exe @prefix -B -c 'import sys;sys.exit(1) if sys.version_info < (3,11) else None;print(sys.executable)' 2>$null)
            if ($LASTEXITCODE -ne 0 -or $result.Count -ne 1) { continue }
            $resolved = ([string]$result[0]).Trim()
            if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { continue }
            $script:outlookPythonExe = $resolved
            return $resolved
        } catch { continue }
    }
    throw 'No usable Python 3.11+ runtime for Outlook CSV persistence (LM_PYTHON_EXE, embedded, python, py -3)'
}

function Merge-OutlookCsv([string]$Root, [string]$Path, [string[]]$Lines, [string]$Kind = 'mail') {
    # The Python writer normalizes legacy headers and atomically unions existing records.
    # Never truncate the destination as a fallback when replacement fails.
    $tmp = $Path + '.' + [guid]::NewGuid().ToString('N') + '.incoming'
    try {
        [IO.File]::WriteAllLines($tmp, $Lines, [Text.UTF8Encoding]::new($true))
        $code = 'import sys;sys.path.insert(0,sys.argv[1]);from collection_state import read_csv,merge_csv;import csv;f=open(sys.argv[3],encoding=''utf-8-sig'',newline='''');h=next(csv.reader(f));f.close();print(merge_csv(sys.argv[2],read_csv(sys.argv[3]),h,kind=sys.argv[4]))'
        $result = & (Get-CollectionPython $Root) -B -c $code (Join-Path $Root 'core') $Path $tmp $Kind
        if ($LASTEXITCODE -ne 0) { throw 'CSV union failed; previous file retained' }
        return [int](@($result)[-1])
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}

function Read-OutlookCsvLines([string]$Root, [string]$Path, [string]$Header) {
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    $code = 'import sys,csv;sys.path.insert(0,sys.argv[1]);from collection_state import read_csv;h=sys.argv[3].split('','');w=csv.writer(sys.stdout,lineterminator=''\n'');w.writerow(h);[w.writerow([str(r.get(k,'''') or '''').replace(''\r'','' '').replace(''\n'','' '') for k in h]) for r in read_csv(sys.argv[2])]'
    $oldEncoding = $env:PYTHONIOENCODING
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        $result = & (Get-CollectionPython $Root) -B -c $code (Join-Path $Root 'core') $Path $Header
        if ($LASTEXITCODE -ne 0) { throw 'Existing CSV cannot be read safely; collection stopped' }
        return @($result)
    } finally { $env:PYTHONIOENCODING = $oldEncoding }
}

function Write-OutlookStatus([string]$Root, [string]$Source, [string]$From, [string]$To,
        [string]$Status, [int]$Rows, [string]$Scope, [string[]]$Reasons = @(), [hashtable]$Extra = @{}) {
    $dir = Join-Path $Root 'data\collection_status'
    [void][IO.Directory]::CreateDirectory($dir)
    $dst = Join-Path $dir ($Source + '.json')
    $tmp = $dst + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    $obj = [ordered]@{ schema = 1; source = $Source; requested_from = $From; requested_to = $To;
        status = $Status; rows = $Rows; scope = $Scope; reasons = @($Reasons);
        finished_at = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0 }
    foreach ($key in $Extra.Keys) { if (-not $obj.Contains($key)) { $obj[$key] = $Extra[$key] } }
    try {
        [IO.File]::WriteAllText($tmp, ($obj | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $dst) { [IO.File]::Replace($tmp, $dst, [NullString]::Value) }
        else { [IO.File]::Move($tmp, $dst) }
    } finally { if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force } }
}

function Get-OutlookMailFolders($Namespace, [bool]$AllFolders, $Problems, [int]$MaxFolders = 1000) {
    # Only DefaultStore, never Namespace.Stores / other accounts / public or shared mailboxes.
    # Keep the directly accessible defaults even if DefaultStore/root enumeration
    # fails. A broader discovery failure must not discard the old local fallback.
    $result = New-Object 'System.Collections.Generic.List[object]'
    $added = New-Object 'System.Collections.Generic.HashSet[string]'
    $sentKey = ''
    foreach ($spec in @(@{ id = 6; name = 'inbox'; field = '[ReceivedTime]' }, @{ id = 5; name = 'sent'; field = '[SentOn]' })) {
        try {
            $folder = $Namespace.GetDefaultFolder($spec.id)
            $key = [string]$folder.EntryID
            if (-not $folder -or -not $key) { throw 'default folder identity unavailable' }
            if ($spec.name -eq 'sent') { $sentKey = $key }
            if ($added.Add($key)) { $result.Add(@{ name = $spec.name; folder = $folder; key = $key; field = $spec.field }) }
        } catch { $Problems.Add('default ' + $spec.name + ' folder inaccessible: ' + $_.Exception.GetType().Name) }
    }
    if (-not $AllFolders) { return $result.ToArray() }
    $exclude = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($id in @(3, 23, 16, 4)) { # Deleted, Junk, Drafts, Outbox: not delivered message evidence
        try { [void]$exclude.Add([string]$Namespace.GetDefaultFolder($id).EntryID) }
        catch { $Problems.Add('excluded default folder identity inaccessible') }
    }
    $queue = New-Object 'System.Collections.Generic.Queue[object]'
    try {
        $store = $Namespace.DefaultStore
        $storeRoot = $store.GetRootFolder()
        if (-not $storeRoot) { throw 'default store root unavailable' }
        $queue.Enqueue(@{ folder = $storeRoot; sent = $false; depth = 0 })
    } catch {
        $Problems.Add('default mailbox root inaccessible; retained accessible Inbox/Sent: ' + $_.Exception.GetType().Name)
        return $result.ToArray()
    }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    while ($queue.Count) {
        $node = $queue.Dequeue(); $folder = $node.folder
        try {
            $key = [string]$folder.EntryID
            if (-not $seen.Add($key) -or $exclude.Contains($key)) { continue }
            if ($seen.Count -gt $MaxFolders -or $node.depth -gt 32) {
                $Problems.Add('default mailbox folder traversal limit reached'); break
            }
            $isSent = $node.sent -or ($sentKey -and $key -eq $sentKey)
            if ([int]$folder.DefaultItemType -eq 0 -and $node.depth -gt 0 -and $added.Add($key)) {
                $result.Add(@{ name = $(if ($isSent) { 'sent' } else { 'inbox' }); folder = $folder;
                              key = $key; field = $(if ($isSent) { '[SentOn]' } else { '[ReceivedTime]' }) })
            }
            foreach ($child in $folder.Folders) {
                $queue.Enqueue(@{ folder = $child; sent = $isSent; depth = $node.depth + 1 })
            }
        } catch { $Problems.Add('default mailbox folder inaccessible: ' + $_.Exception.GetType().Name) }
    }
    return $result.ToArray()
}

function Get-OutlookContext($Item, [int]$Limit, [bool]$Enabled, $Problems) {
    if (-not $Enabled) { return @('', '') }
    try {
        $raw = $Item.Body
        if ($null -eq $raw) { throw 'message body property unavailable' }
        $body = (([string]$raw) -replace '\s+', ' ').Trim()
        $truncated = $body.Length -gt $Limit
        if ($truncated) { $body = $body.Substring(0, $Limit) }
        return @($body, $(if ($truncated) { 'true' } else { 'false' }))
    } catch {
        $Problems.Add('message body inaccessible: ' + $_.Exception.GetType().Name)
        return @('', 'unknown')
    }
}
