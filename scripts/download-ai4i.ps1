[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$destination = Join-Path $projectRoot "data\raw"
$archive = Join-Path $destination "ai4i2020.zip"
$sourceUrl = "https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip"
$expectedHash = "DC6630CD9B1F0F853922FAD78A1B6436570D3F1EC863F1DD5C4340AC56BC8A8E"

New-Item -ItemType Directory -Force -Path $destination | Out-Null
Invoke-WebRequest -Uri $sourceUrl -OutFile $archive
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
Remove-Item -LiteralPath $archive

$csv = Get-ChildItem -LiteralPath $destination -Filter "*.csv" | Select-Object -First 1
if (-not $csv) { throw "The downloaded archive did not contain a CSV file." }
if ($csv.Name -ne "ai4i2020.csv") {
    Move-Item -LiteralPath $csv.FullName -Destination (Join-Path $destination "ai4i2020.csv") -Force
    $csv = Get-Item -LiteralPath (Join-Path $destination "ai4i2020.csv")
}

$hash = Get-FileHash -LiteralPath $csv.FullName -Algorithm SHA256
if ($hash.Hash -ne $expectedHash) {
    throw "Dataset checksum mismatch. Expected $expectedHash but received $($hash.Hash)."
}
Write-Host "Downloaded public dataset to $($csv.FullName)"
Write-Host "SHA-256: $($hash.Hash)"
Write-Host "The file is ignored by Git. Review data/README.md before use."
