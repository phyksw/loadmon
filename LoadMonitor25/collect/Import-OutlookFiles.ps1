# Import explicitly selected .msg files through classic Outlook's documented
# NameSpace.OpenSharedItem. Never mounts PST/OST, saves a message or starts a send.
# Exit 0 = selected files examined, 2 = partial/blocked, 1 = failed.
param([string]$ManifestPath = '', [string[]]$Paths = @(), [string]$From = '', [string]$To = '',
      [int]$BudgetSec = 300, [int]$MaxFileMB = 100)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $PSScriptRoot 'Outlook-Collection.ps1')
$script:msgRows = 0; $script:msgAttempted = 0; $script:msgSkipped = 0
$problems = New-Object 'System.Collections.Generic.List[string]'
$scope = 'explicitly selected MSG files only; original files are not saved or modified; attachments excluded; mailbox coverage unverified'
$started = [Diagnostics.Stopwatch]::StartNew()
$selected = @(); $addresses = @(); $ns = $null; $ol = $null
$progressPath = Join-Path $root 'data\collection_status\outlook_files_progress.json'

function Complete-MessageImport([string]$Status, [int]$Code) {
    Write-OutlookStatus $root 'outlook_files' $From $To $Status $script:msgRows $scope @($problems) @{
        mail_status='partial'; calendar_status='skipped'; mail_rows=$script:msgRows; server_complete=$false;
        selected_files=$selected.Count; attempted_files=$script:msgAttempted; skipped_files=$script:msgSkipped;
        completed_units=$script:msgAttempted; total_units=$selected.Count; original_files_modified=$false
    }
    $summary = [ordered]@{status=$Status;rows=$script:msgRows;selected=$selected.Count;attempted=$script:msgAttempted;
        status_path=(Join-Path $root 'data\collection_status\outlook_files.json');reasons=@($problems)}
    Write-Host ($summary | ConvertTo-Json -Compress -Depth 4)
    return $Code
}

function Convert-OutlookSelectedMessage($Item, [string]$Identity, [string[]]$SelfAddresses,
        [datetime]$Start, [datetime]$End, [int]$ContextChars, [bool]$StoreSubject, [bool]$StoreBody, $Problems) {
    if ([int]$Item.Class -ne 43) { return $null }
    if ($null -ne $Item.Sent -and -not [bool]$Item.Sent) { return $null }
    $box = Get-OutlookDirection $Item '' $SelfAddresses
    if ($box -ne 'sent') {
        # A standalone file has no Inbox folder provenance. Prove a recipient
        # match or retain unknown direction instead of inventing inbox activity.
        $box = 'unknown'
        $own=@($SelfAddresses | ForEach-Object {([string]$_).Trim().ToLowerInvariant()} | Where-Object {$_})
        $recipients=New-Object 'System.Collections.Generic.List[string]'
        try {
            foreach($recipient in $Item.Recipients) {
                $address=''
                try {$address=[string]$recipient.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x39FE001E')} catch {}
                if (-not $address) {try {$address=[string]$recipient.Address} catch {}}
                if ($address) {$recipients.Add($address.Trim().ToLowerInvariant())}
            }
        } catch {}
        try {
            foreach($match in [regex]::Matches(([string]$Item.To+';'+[string]$Item.CC),'[A-Za-z0-9.!#$%&''*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+')) {
                $recipients.Add($match.Value.Trim().ToLowerInvariant())
            }
        } catch {}
        if (@($recipients | Where-Object {$own -contains $_}).Count) { $box='inbox' }
    }
    $stamp = $(if ($box -eq 'sent') { $Item.SentOn } else { $Item.ReceivedTime })
    if ($null -eq $stamp -or [datetime]$stamp -lt [datetime]'1900-01-01') { throw 'original message timestamp unavailable' }
    if ([datetime]$stamp -lt $Start -or [datetime]$stamp -ge $End) { return $null }
    $context = @(Get-OutlookContext $Item $ContextChars ($StoreSubject -and $StoreBody -and $ContextChars -gt 0) $Problems)
    $subject=''; $conversation=''
    if ($StoreSubject) { $subject=[string]$Item.Subject; $conversation=[string]$Item.ConversationTopic }
    $conversationId=''; try { $conversationId=[string]$Item.ConversationID } catch {}
    return [pscustomobject][ordered]@{
        box=$box;time=([datetime]$stamp).ToString('yyyy-MM-dd HH:mm');sender=[string]$Item.SenderName;
        subject=$subject;conversation=$conversation;rcv='unknown';time_precision=$(if ($box -eq 'unknown') {'unknown'} else {'minute'});
        context_excerpt=[string]$context[0];context_truncated=[string]$context[1];source_id=$Identity;
        source_kind='outlook_msg';source_url='';conversation_id=$conversationId;folder='selected MSG';account='';
        raw_body_b64=[string]$context[2]
    }
}

function Get-SelectedMessagePlan([string[]]$SelectedPaths, [string]$CheckpointPath,
        [string]$StartDate, [string]$EndDate, [bool]$SubjectEnabled, [bool]$BodyEnabled,
        [int]$ExcerptChars, [string[]]$SelfAddresses, [string]$CsvPath = '') {
    $signature=Get-OutlookTextHash ((@($StartDate,$EndDate,[string]$SubjectEnabled,[string]$BodyEnabled,[string]$ExcerptChars) + @($SelfAddresses|Sort-Object) + @($SelectedPaths|Sort-Object)) -join "`n")
    $state=@{signature=$signature;complete=$false;files=@{}}
    try {
        $prior=Get-Content -LiteralPath $CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($prior.signature -eq $signature -and -not $prior.complete) {
            foreach($entry in $prior.files.PSObject.Properties) { $state.files[$entry.Name]=@{done=[bool]$entry.Value.done;hash=[string]$entry.Value.hash;source_id=[string]$entry.Value.source_id;no_row=[bool]$entry.Value.no_row} }
        }
    } catch {}
    if ($CsvPath) {
        $stored = Get-OutlookStoredSourceIds $root $CsvPath
        foreach ($entry in $state.files.Values) {
            if ($entry.done -and -not $entry.no_row -and (-not $entry.source_id -or -not $stored.Contains([string]$entry.source_id))) { $entry.done = $false }
        }
    }
    $ordered=@($SelectedPaths | Sort-Object @{Expression={ $key=Get-OutlookTextHash ($_.ToLowerInvariant()); [bool]$state.files[$key].done }})
    return @{state=$state;paths=$ordered}
}

function Test-SelectedMessageComplete($State, [string]$Path, [string]$FileHash) {
    $key=Get-OutlookTextHash ($Path.ToLowerInvariant())
    return ($State.files[$key].done -and $State.files[$key].hash -eq $FileHash)
}

try {
    if (-not $From -or -not $To) { throw 'From and To are required (yyyy-MM-dd)' }
    $start=[datetime]::ParseExact($From,'yyyy-MM-dd',$null)
    $end=([datetime]::ParseExact($To,'yyyy-MM-dd',$null)).AddDays(1)
    if ($end -le $start) { throw 'Invalid requested date range' }
    if ($ManifestPath) {
        $manifest=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $Paths=@($manifest.paths); $addresses=@($manifest.ownAddresses | ForEach-Object { ([string]$_).Trim().ToLowerInvariant() })
        if ($null -ne $manifest.expectedCount -and [int]$manifest.expectedCount -ne $Paths.Count) { throw 'Selected file count mismatch' }
    }
    if (-not $Paths.Count -or $Paths.Count -gt 200) { throw 'Select between 1 and 200 MSG files' }
    $selected=@($Paths | Select-Object -Unique)
    $limit=[Math]::Max(1,[Math]::Min(1024,$MaxFileMB))*1MB
    foreach ($path in $selected) {
        if ([IO.Path]::GetExtension($path).ToLowerInvariant() -ne '.msg' -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw 'Only existing explicitly selected .msg files are supported. Open PST in classic Outlook and use connected-store collection.'
        }
    }
    $cfg=$null; try { $cfg=Get-Content -LiteralPath (Join-Path $root 'config\config.json') -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
    $contextChars=4000; $storeSubject=$true; $storeBody=$true
    if ($null -ne $cfg.storeMailSubject) { $storeSubject=[bool]$cfg.storeMailSubject }
    if ($null -ne $cfg.collection.mailBody) { $storeBody=[bool]$cfg.collection.mailBody }
    if ($null -ne $cfg.collection.contextChars) { $contextChars=[Math]::Max(0,[Math]::Min(20000,[int]$cfg.collection.contextChars)) }
    $selected=@($selected | ForEach-Object {(Get-Item -LiteralPath $_).FullName})
    $out=Join-Path $root 'data\outlook\mail.csv'
    $plan=Get-SelectedMessagePlan $selected $progressPath $From $To $storeSubject $storeBody $contextChars $addresses $out
    $progress=$plan.state
    # A completed run refreshes all selected files next time. An interrupted run
    # starts with unfinished files, validating byte hashes before skipping prior
    # successes. No plaintext source paths are written to the checkpoint.
    $selected=@($plan.paths)
    Write-OutlookProgress $progressPath $progress
    Write-OutlookStatus $root 'outlook_files' $From $To 'partial' 0 $scope @('selected-file import in progress') @{selected_files=$selected.Count}
    try { $ol=[Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
    catch { try { $ol=New-Object -ComObject Outlook.Application } catch { throw 'Classic Outlook COM is unavailable. New Outlook alone cannot provide OpenSharedItem; use an EML export or install/open classic Outlook.' } }
    $ns=$ol.GetNamespace('MAPI')
    $out=Join-Path $root 'data\outlook\mail.csv'; [void][IO.Directory]::CreateDirectory((Split-Path -Parent $out))
    foreach ($path in $selected) {
        if ($started.Elapsed.TotalSeconds -ge [Math]::Max(1,$BudgetSec)) { $problems.Add('file import time budget reached; rerun selected files to continue'); break }
        $script:msgAttempted++; $item=$null
        try {
            $file=Get-Item -LiteralPath $path
            if ($file.Length -gt $limit) { $script:msgSkipped++; $problems.Add('selected MSG exceeds configured size limit'); continue }
            $hash=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $fileKey=Get-OutlookTextHash ($file.FullName.ToLowerInvariant())
            if (Test-SelectedMessageComplete $progress $file.FullName $hash) { continue }
            $progress.files[$fileKey]=@{done=$false;hash=$hash}
            $item=$ns.OpenSharedItem($file.FullName)
            $row=Convert-OutlookSelectedMessage $item ('derived:outlook-msg-sha256:'+ $hash) $addresses $start $end $contextChars $storeSubject $storeBody $problems
            if ($row) {
                $lines=@($row | ConvertTo-Csv -NoTypeInformation)
                $null=Merge-OutlookCsv $root $out $lines 'mail'
                $script:msgRows++
                $progress.files[$fileKey].source_id = [string]$row.source_id
            } else { $script:msgSkipped++ }
            $progress.files[$fileKey].no_row = (-not $row)
            if (-not $row -or $row.context_truncated -ne 'unknown') { $progress.files[$fileKey].done=$true }
            Write-OutlookProgress $progressPath $progress
            Write-OutlookStatus $root 'outlook_files' $From $To 'partial' $script:msgRows $scope @($problems) @{selected_files=$selected.Count;attempted_files=$script:msgAttempted;mail_status='partial'}
        } catch { $problems.Add('selected message could not be read or saved: '+$_.Exception.GetType().Name) }
        finally {
            if ($item) { try { $item.Close(1) } catch {}; try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($item) } catch {} }
        }
    }
    if ($problems.Count -or $script:msgAttempted -lt $selected.Count) { $code=Complete-MessageImport 'partial' 2 }
    else { $progress.complete=$true; Write-OutlookProgress $progressPath $progress; $code=Complete-MessageImport 'complete' 0 }
} catch {
    $problems.Add($_.Exception.Message)
    $code=Complete-MessageImport 'failed' 1
} finally {
    if ($ns) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ns) } catch {} }
    if ($ol) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ol) } catch {} }
}
exit $code
