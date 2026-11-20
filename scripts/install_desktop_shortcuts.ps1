# Creates "Drama Recap Studio" shortcuts (Desktop + Start Menu) that open the desktop app.
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\install_desktop_shortcuts.ps1
$repo = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $repo ".venv-recap\Scripts\pythonw.exe"
$icon = Join-Path $repo "src\recap_engine\web\icon.ico"
if (-not (Test-Path $pyw)) { Write-Error ".venv-recap not found - install it first (docs/drama-recap-studio.md)"; exit 1 }
$shell = New-Object -ComObject WScript.Shell
$targets = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))
foreach ($dir in $targets) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "Drama Recap Studio.lnk"))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "-m recap_engine.desktop"
    $lnk.WorkingDirectory = $repo
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Description = "Drama Recap Studio (local)"
    $lnk.Save()
    Write-Output "shortcut: $(Join-Path $dir 'Drama Recap Studio.lnk')"
}
