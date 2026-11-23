# Removes the hidden UTF-8 byte-order mark that Windows PowerShell 5.1 adds with `Set-Content -Encoding utf8`.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File .\fix_bom.ps1
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$exts = '.py', '.ini', '.yml', '.yaml', '.txt', '.md', '.sql', '.html', '.ps1', '.example', '.csv', '.json'
Get-ChildItem -Recurse -File -Force |
  Where-Object { $_.FullName -notmatch '\\(\.venv|\.git|__pycache__|node_modules)\\' } |
  Where-Object { $exts -contains $_.Extension -or $_.Name -in 'Dockerfile', '.gitignore', '.dockerignore', '.env', '.env.example' } |
  ForEach-Object {
    $bytes = [IO.File]::ReadAllBytes($_.FullName)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
      $text = [IO.File]::ReadAllText($_.FullName)
      [IO.File]::WriteAllText($_.FullName, $text, $utf8NoBom)
      Write-Host "Fixed BOM: $($_.FullName)"
    }
  }
Write-Host "Done."
