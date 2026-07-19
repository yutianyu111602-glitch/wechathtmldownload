param(
  [string]$OutRoot = "",
  [string]$TitleRegex = "weekly_activity_miniprogram|微信开发者工具|WeChat DevTools",
  [int]$MinWidth = 640,
  [int]$MinHeight = 480,
  [switch]$Maximize
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class User32WindowProbe {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

  [DllImport("user32.dll")]
  public static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);

  [DllImport("user32.dll")]
  public static extern bool IsWindowVisible(IntPtr hWnd);

  [DllImport("user32.dll", SetLastError = true)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

  [DllImport("user32.dll", SetLastError = true)]
  public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);

  [DllImport("user32.dll", SetLastError = true)]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

  [DllImport("user32.dll")]
  public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);

  [StructLayout(LayoutKind.Sequential)]
  public struct RECT {
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
  }
}
"@

function Get-WindowList {
  $windows = New-Object System.Collections.Generic.List[object]
  $callback = [User32WindowProbe+EnumWindowsProc]{
    param([IntPtr]$hWnd, [IntPtr]$lParam)

    if (-not [User32WindowProbe]::IsWindowVisible($hWnd)) {
      return $true
    }

    $titleBuilder = New-Object System.Text.StringBuilder 512
    [void][User32WindowProbe]::GetWindowText($hWnd, $titleBuilder, $titleBuilder.Capacity)
    $title = $titleBuilder.ToString()
    if ([string]::IsNullOrWhiteSpace($title)) {
      return $true
    }

    $classBuilder = New-Object System.Text.StringBuilder 256
    [void][User32WindowProbe]::GetClassName($hWnd, $classBuilder, $classBuilder.Capacity)
    $className = $classBuilder.ToString()

    $windowPid = [uint32]0
    [void][User32WindowProbe]::GetWindowThreadProcessId($hWnd, [ref]$windowPid)

    $rect = New-Object User32WindowProbe+RECT
    if (-not [User32WindowProbe]::GetWindowRect($hWnd, [ref]$rect)) {
      return $true
    }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -lt $MinWidth -or $height -lt $MinHeight) {
      return $true
    }

    $processName = ""
    try {
      $processName = (Get-Process -Id ([int]$windowPid) -ErrorAction Stop).ProcessName
    } catch {
      $processName = ""
    }

    $windows.Add([pscustomobject]@{
      hwnd = $hWnd.ToInt64()
      title = $title
      className = $className
      processId = [int]$windowPid
      processName = $processName
      left = $rect.Left
      top = $rect.Top
      right = $rect.Right
      bottom = $rect.Bottom
      width = $width
      height = $height
      titleMatch = [bool]($title -match $TitleRegex)
      processMatch = [bool]($processName -match "微信开发者工具|wechatdevtools|WeChat")
    })
    return $true
  }
  [void][User32WindowProbe]::EnumWindows($callback, [IntPtr]::Zero)
  return $windows
}

if ([string]::IsNullOrWhiteSpace($OutRoot)) {
  $repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
  $stamp = Get-Date -Format "yyyy-MM-ddTHH-mm-ss-fff"
  $OutRoot = Join-Path $repoRoot "apps\weekly_activity_miniprogram\test-artifacts\devtools-window-visible-screenshot-$stamp"
}

New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

$windows = @(Get-WindowList)
$candidates = @($windows | Where-Object {
  $_.titleMatch -or $_.processMatch
} | Sort-Object @{ Expression = "titleMatch"; Descending = $true }, @{ Expression = "processMatch"; Descending = $true }, @{ Expression = "width"; Descending = $true })

if ($candidates.Count -lt 1) {
  $report = [pscustomobject]@{
    ok = $false
    reason = "no_matching_visible_devtools_window"
    titleRegex = $TitleRegex
    outRoot = $OutRoot
    candidates = @()
    visibleWindowSample = @($windows | Select-Object -First 20)
    safety = [pscustomobject]@{
      miniProgramUploadExecuted = $false
      cloudRunDeployExecuted = $false
      previewQrGenerated = $false
      reviewSubmitted = $false
      publicReleaseExecuted = $false
      productionDbWriteExecuted = $false
    }
  }
  $report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path (Join-Path $OutRoot "report.json")
  Write-Output ($report | ConvertTo-Json -Depth 8)
  exit 1
}

$target = $candidates[0]
$hwnd = [IntPtr]::new([int64]$target.hwnd)
$showCommand = if ($Maximize) { 3 } else { 9 }
[void][User32WindowProbe]::ShowWindow($hwnd, $showCommand)
[void][User32WindowProbe]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 900

$rect = New-Object User32WindowProbe+RECT
[void][User32WindowProbe]::GetWindowRect($hwnd, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top

$pngPath = Join-Path $OutRoot "devtools-window-visible.png"
$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
  $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, ([System.Drawing.Size]::new($width, $height)))
  $bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
  $graphics.Dispose()
  $bitmap.Dispose()
}

$file = Get-Item -LiteralPath $pngPath
$sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $pngPath).Hash
$report = [pscustomobject]@{
  ok = $true
  captureKind = "visible_windows_desktop_capture"
  acceptedAsMiniProgramPixelProof = $false
  proofLimit = "Captures the visible WeChat DevTools desktop window only. It proves window state and pixels on screen, not automator App.captureScreenshot success or mini-program page semantics."
  screenshotPath = $pngPath
  screenshotBytes = $file.Length
  screenshotSha256 = $sha256
  window = [pscustomobject]@{
    hwnd = $target.hwnd
    title = $target.title
    className = $target.className
    processId = $target.processId
    processName = $target.processName
    left = $rect.Left
    top = $rect.Top
    right = $rect.Right
    bottom = $rect.Bottom
    width = $width
    height = $height
  }
  titleRegex = $TitleRegex
  outRoot = $OutRoot
  maximizeRequested = [bool]$Maximize
  safety = [pscustomobject]@{
    miniProgramUploadExecuted = $false
    cloudRunDeployExecuted = $false
    previewQrGenerated = $false
    reviewSubmitted = $false
    publicReleaseExecuted = $false
    productionDbWriteExecuted = $false
  }
}

$report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path (Join-Path $OutRoot "report.json")
Write-Output ($report | ConvertTo-Json -Depth 8)
