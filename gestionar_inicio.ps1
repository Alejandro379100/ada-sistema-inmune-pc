# ==========================================
#   gestionar_inicio.ps1
#   Lanzador inteligente del modo terminal de Ada.
#
#   Antes simplemente corría python.exe app.py sin
#   preguntar nada -- si Ada ya estaba corriendo invisible
#   (arranque automático al iniciar sesión), esto generaba
#   una SEGUNDA copia compitiendo por el mismo ada_cerebro.db
#   al mismo tiempo. Ahora primero revisa, y deja elegir.
# ==========================================

$yaCorriendo = Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*app.py*--invisible*' }

if ($yaCorriendo) {
    Write-Host ""
    Write-Host "  Ada ya esta corriendo invisible en segundo plano." -ForegroundColor Yellow
    Write-Host "  Para hablarle por terminal hay que cerrar esa copia primero"
    Write-Host "  (si no, quedan dos Adas compitiendo por la misma base de datos)."
    Write-Host ""
    $resp = Read-Host "  Cerrar la copia invisible y abrir el modo terminal ahora? (s/n)"
    if ($resp -eq "s") {
        $yaCorriendo | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Start-Sleep -Milliseconds 500
        Write-Host "  Listo, copia invisible cerrada. Iniciando modo terminal..."
        Write-Host ""
    } else {
        Write-Host "  Dejando a Ada como esta, invisible en segundo plano."
        exit
    }
}

& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\app.py"
