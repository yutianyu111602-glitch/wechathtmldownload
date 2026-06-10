
$ErrorActionPreference = 'Stop'
$danger = @('Get-ChildItem.*D:.*-Recurse', 'robocopy.*D:', 'find.*D:\\.*-type f', 'tar.*D:', 'zip.*D:', 'Remove-Item.*D:', 'rd.*D:', 'del.*D:')
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (
        ($_.Name -match 'python|node|cmd|powershell' -and $_.CommandLine -match 'Get-ChildItem.*-Recurse.*[Dd]:') -or
        ($_.Name -match 'python|node' -and $_.CommandLine -match '(os\\.walk|os\\.scandir|shutil\\.rmtree|glob\\.glob).*[Dd]:') -or
        ($_.Name -match 'python|node|cmd|robocopy' -and $_.CommandLine -match 'robocopy.*[Dd]:') -or
        ($_.Name -match 'python|node|cmd' -and $_.CommandLine -match '(Remove-Item|rd|del|rmdir).*-Recurse.*[Dd]:')
    ) -and $_.CommandLine -notmatch 'powershell.exe.*-NoProfile.*-File'
} | Select-Object ProcessId, Name, @{N='Cmd';E={$_.CommandLine.Substring(0,[Math]::Min(300,$_.CommandLine.Length))}}, CreationDate

if ($procs) {
    $procs | ConvertTo-Json -Depth 3 -Compress
} else {
    Write-Output 'CLEAN'
}
