# Pruebas de Ada

Estas pruebas usan **pytest** y corren en cualquier sistema (Windows, Linux, Mac) —
`conftest.py` simula `winreg` y `wmi` (que solo existen en Windows) para que
puedas correrlas incluso si no estás en tu PC de Windows.

## Instalar (una sola vez)

```
pip install -r requirements-dev.txt
```

## Correr todas las pruebas

```
pytest tests/ -v
```

## Ver qué porcentaje del código realmente se prueba

```
pytest tests/ --cov=. --cov-report=term-missing
```

## Qué cubren estas pruebas ahora mismo

- `test_memoria.py` — historial médico (que guarde varias muestras por día,
  no solo una), migración de bases de datos viejas, el cooldown de 24h que
  evita repetir reparaciones, y el límite de tamaño de la base de datos.
- `test_medico.py` — el médico autónomo: que Groq solo pueda ejecutar
  acciones de la lista blanca, que respete el riesgo (bajo se ejecuta solo,
  alto solo se recomienda), y que no repita la misma reparación.
- `test_comandos.py` — el bug real de reintentos de contraseña, y el
  comando para revisar el historial de decisiones.
- `test_puntuacion.py` — que el reconocimiento de procesos elija la
  coincidencia más específica, no la primera que encuentre.

## Cómo agregar una prueba nueva

1. Si necesitas una base de datos temporal, pide el fixture `db_temporal`
   como argumento de tu función de prueba — ya viene lista, aislada, y se
   borra sola al terminar.
2. Si tu prueba llama código que ejecutaría comandos reales de Windows
   (DISM, SFC, taskkill, etc.), usa `monkeypatch` para reemplazar esa
   función específica antes de llamarla — no dejes que corra de verdad.
3. Nombra el archivo `test_<algo>.py` y cada función `test_<qué prueba>` —
   pytest los encuentra solo, no hay que registrarlos en ningún lado.
