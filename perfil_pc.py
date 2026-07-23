# ==========================================
#   perfil_pc.py - ADN de la Máquina
#   Ada conoce este PC de memoria.
#   Cada decisión que toma parte de aquí.
# ==========================================

import os

# Antes estas rutas tenían "USUARIO" escrito literal y nunca coincidían
# con nada real en el disco (Ada las ignoraba en silencio). Ahora se
# arman con el usuario real de Windows, sea cual sea.
_HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")

PERFIL = {
    "nombre_pc": "MI-PC",  # <- poné el nombre real de tu equipo
    "propietario": "TU-NOMBRE",  # <- poné tu nombre
    "proposito_principal": "programacion",  # Ada siempre protege este fin

    "cpu": {
        "nombre": "Intel Core i5-8350U",
        "nucleos_fisicos": 4,
        "nucleos_logicos": 8,
        "frecuencia_base_mhz": 1700,
        "frecuencia_max_mhz": 3600,  # turbo boost real del i5-8350U
        "cache_l2_kb": 1024,
        "cache_l3_kb": 6144,
        "generacion": "8va generacion Intel Kaby Lake-R",
        "socket": "U3E1",
        "arquitectura": "x86_64"
    },

    "ram": {
        "total_gb": 16,
        "slots_usados": 1,
        "slots_totales": 1,       # soldada — NO se puede ampliar
        "ampliable": False,
        "tipo": "DDR4",
        "velocidad_mhz": 2400,
        "fabricante": "SK Hynix",
        "modelo": "HMA82GS6CJR8N-VK",
        # CRÍTICO: GPU integrada comparte RAM del sistema
        "gpu_comparte_ram": True,
        "ram_reservada_gpu_aprox_gb": 1.0,
        # RAM real disponible para apps = ~15GB
        "umbral_critico_pct": 80,   # Ada actúa sola
        "umbral_alerta_pct": 65,    # Ada avisa
        "meta_libre_para_programar_gb": 6.0  # mínimo para VS Code fluido
    },

    "disco": {
        "modelo": "INTEL SSDPEKKF256G8L",
        "tipo": "NVMe SSD",
        "interfaz": "PCIe NVMe",
        "total_gb": 238,
        "firmware": "L15P",
        "serial": "OCULTO",  # <- serial real removido para GitHub
        "umbral_alerta_libre_gb": 15,
        "umbral_critico_libre_gb": 8,
        # NVMe — Ada nunca desfragmenta (daña SSDs)
        "desfragmentar": False
    },

    "gpu": {
        "nombre": "Intel UHD Graphics 620",
        "fabricante": "Intel",
        "vram_mb": 1024,
        "tipo": "Integrada — comparte RAM del sistema",
        "driver_version": "31.0.101.2135",
        "driver_fecha": "2025-03-06",
        "resolucion": "1920x1080",
        "refresh_hz": 60,
        # No tiene GPU dedicada — Ada no intenta instalar drivers de NVIDIA/AMD
        "gpu_dedicada": False
    },

    "placa_madre": {
        "fabricante": "Lenovo",
        "modelo": "OCULTO",  # <- modelo real removido para GitHub
        "version": "OCULTO",
        "serial": "OCULTO"
    },

    "bios": {
        "fabricante": "Lenovo",
        "version": "N24ET81W (1.56)",
        "fecha": "2025-09-06",
        "serial_pc": "OCULTO"
        # BIOS actualizado — Ada NO sugiere actualizar BIOS (riesgo alto)
    },

    "bateria": {
        "tiene_bateria": True,
        "tipo": "laptop",
        # Ada avisa cuando baja del 20% si no está enchufada
        "umbral_alerta_pct": 20
    },

    "red": {
        "wifi": True,
        "velocidad_wifi_mbps": 866,
        "ethernet": False
    },

    "sistema_operativo": {
        "nombre": "Windows 11",
        "build": "10.0.26200",
        "arquitectura": "AMD64",
        "python": "3.14.3"
    },

    # Procesos que Ada NUNCA toca bajo ninguna circunstancia
    "procesos_criticos": [
        "system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
        "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe",
        "taskhostw.exe", "spoolsv.exe", "audiodg.exe", "fontdrvhost.exe",
        "sihost.exe", "ctfmon.exe", "searchindexer.exe", "wuauclt.exe",
        "msiexec.exe", "conhost.exe", "dllhost.exe", "rundll32.exe",
        "regsvr32.exe", "wmiprvse.exe", "msmpeng.exe", "securityhealthservice.exe",
        "antimalware service executable", "ntoskrnl.exe", "registry",
        "memory compression", "memcompression", "runtimebroker.exe",
        "startmenuexperiencehost.exe", "shellexperiencehost.exe",
        "applicationframehost.exe", "systemsettings.exe", "sgrmbroker.exe",
        "securityhealthsystray.exe", "wlanext.exe", "dashost.exe"
    ],

    # Rutas que Ada NUNCA modifica sin permiso explícito
    "rutas_protegidas": [
        "C:\\Windows",
        "C:\\Windows\\System32",
        "C:\\Windows\\SysWOW64",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        os.path.join(_HOME, "Documents"),
        os.path.join(_HOME, "Desktop"),
        "C:\\ProgramData\\Microsoft"
    ],

    # Rutas seguras para limpiar
    "rutas_limpieza_segura": [
        "%TEMP%",
        "%TMP%",
        "C:\\Windows\\Temp",
        os.path.join(_HOME, "AppData", "Local", "Temp"),
        os.path.join(_HOME, "AppData", "Local", "Microsoft", "Windows", "INetCache"),
        os.path.join(_HOME, "AppData", "Local", "Microsoft", "Windows", "Temporary Internet Files"),
        "C:\\Windows\\Prefetch",
        os.path.join(_HOME, "AppData", "Local", "CrashDumps"),
        "C:\\Windows\\SoftwareDistribution\\Download",
        "C:\\$Recycle.Bin"
    ],

    # Programas del usuario detectados (se actualiza en runtime)
    "programas_usuario": [
        "Visual Studio Code",
        "Google Chrome",
        "WhatsApp",
        "Microsoft Edge",
        "Git",
        "Python",
        "Postman",
        "MongoDB Compass",
        "Spotify"
    ]
}