Get-CimInstance Win32_PnPEntity | Where-Object { $_.Caption -match 'COM\d+' } | Select-Object Caption
