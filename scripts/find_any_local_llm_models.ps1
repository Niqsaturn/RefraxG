[CmdletBinding()]
param(
    [switch]$DeepScan,
    [switch]$EmitJson
)

$ErrorActionPreference = 'SilentlyContinue'

$results = New-Object System.Collections.Generic.List[object]
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$searched = New-Object System.Collections.Generic.List[string]
$extSet = @('.gguf', '.safetensors', '.bin')
$metaNames = @('config.json', 'tokenizer.json', 'generation_config.json', 'modelfile')

function Add-FoundModel {
    param(
        [string]$Name,
        [string]$Path,
        [string]$Kind,
        [double]$Confidence,
        [string]$Detector,
        [double]$SizeGb,
        [hashtable]$Details
    )
    if ([string]::IsNullOrWhiteSpace($Name) -or [string]::IsNullOrWhiteSpace($Path)) { return }
    $key = "$Name|$Path"
    if ($seen.Contains($key)) { return }
    [void]$seen.Add($key)
    $results.Add([pscustomobject]@{
        name       = $Name
        path       = $Path
        kind       = $Kind
        confidence = [math]::Round($Confidence, 3)
        detector   = $Detector
        size_gb    = [math]::Round($SizeGb, 3)
        details    = $Details
    }) | Out-Null
}

function Add-SearchedPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not $searched.Contains($Path)) { [void]$searched.Add($Path) }
}

function Scan-Extensions([string]$Root, [switch]$Recurse) {
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Add-SearchedPath $Root
    $depth = if ($Recurse) { '-Recurse' } else { '' }
    $cmd = "Get-ChildItem -LiteralPath '$Root' -File $depth"
    $files = Invoke-Expression $cmd
    foreach ($f in $files) {
        $ext = $f.Extension.ToLowerInvariant()
        if ($extSet -contains $ext) {
            $kind = if ($ext -eq '.gguf') { 'gguf' } elseif ($ext -eq '.safetensors') { 'safetensors' } else { 'weights' }
            Add-FoundModel -Name $f.BaseName -Path $f.FullName -Kind $kind -Confidence 0.95 -Detector 'extension_scan' -SizeGb ($f.Length/1GB) -Details @{ extension=$ext; source='extension_scan' }
        }
    }
}

function Scan-Metadata([string]$Root, [switch]$Recurse) {
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Add-SearchedPath $Root
    $depth = if ($Recurse) { '-Recurse' } else { '' }
    $cmd = "Get-ChildItem -LiteralPath '$Root' -Directory $depth"
    $dirs = Invoke-Expression $cmd
    foreach ($d in $dirs) {
        $hits = @()
        foreach ($m in $metaNames) {
            if (Test-Path -LiteralPath (Join-Path $d.FullName $m)) { $hits += $m }
        }
        if ($hits.Count -ge 2) {
            $sz = 0
            Get-ChildItem -LiteralPath $d.FullName -File | ForEach-Object { $sz += $_.Length }
            Add-FoundModel -Name $d.Name -Path $d.FullName -Kind 'metadata_dir' -Confidence 0.8 -Detector 'metadata_scan' -SizeGb ($sz/1GB) -Details @{ matched_files=$hits; source='metadata_scan' }
        }
    }
}

$roots = New-Object System.Collections.Generic.List[string]
@($env:ANTENNAMAP_MODEL_SEARCH_PATHS, $env:LOCALAPPDATA, $env:APPDATA, $env:USERPROFILE) | ForEach-Object {
    if ($_ -and -not $roots.Contains($_)) { [void]$roots.Add($_) }
}
if ($env:ProgramData) { [void]$roots.Add((Join-Path $env:ProgramData 'Ollama\models')) }
if ($env:HUGGINGFACE_HUB_CACHE) { [void]$roots.Add($env:HUGGINGFACE_HUB_CACHE) }
if ($env:HF_HOME) { [void]$roots.Add((Join-Path $env:HF_HOME 'hub')) }

$recurse = $DeepScan.IsPresent
foreach ($r in $roots) {
    Scan-Extensions -Root $r -Recurse:$recurse
    Scan-Metadata -Root $r -Recurse:$recurse
}

$ollamaBin = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaBin) {
    $ollamaJson = & ollama list --json 2>$null
    if ($LASTEXITCODE -eq 0 -and $ollamaJson) {
        $entries = $ollamaJson | ConvertFrom-Json
        foreach ($e in $entries) {
            $name = if ($e.model) { $e.model } else { $e.name }
            $sizeb = [double]($e.size)
            Add-FoundModel -Name $name -Path "ollama:$name" -Kind 'ollama' -Confidence 0.99 -Detector 'ollama_cli' -SizeGb ($sizeb/1GB) -Details @{ digest=$e.digest; modified_at=$e.modified_at; source='ollama_cli' }
        }
    }
}

$ollamaStore = Join-Path $env:USERPROFILE '.ollama\models'
if (Test-Path -LiteralPath $ollamaStore) {
    Add-SearchedPath $ollamaStore
    Get-ChildItem -LiteralPath $ollamaStore -Recurse -File | Where-Object { $_.Extension -eq '.bin' -or $_.Extension -eq '.gguf' } | ForEach-Object {
        Add-FoundModel -Name $_.BaseName -Path $_.FullName -Kind 'ollama_blob' -Confidence 0.6 -Detector 'ollama_storage' -SizeGb ($_.Length/1GB) -Details @{ source='ollama_storage' }
    }
}

$payload = [pscustomobject]@{
    findings = $results
    searched_paths = $searched
    deep_scan = $DeepScan.IsPresent
}

if ($EmitJson) {
    $payload | ConvertTo-Json -Depth 8 -Compress
} else {
    $results | Format-Table -AutoSize
}
