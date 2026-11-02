# J.A.R.V.I.S. — Asistente personal de voz con IA

Asistente de voz para Windows que entiende lenguaje natural y controla el **PC**, un **teléfono Android** y **Alexa**. Le hablas ("Hey Jarvis, activa el modo trabajo") y un modelo de IA decide qué herramientas ejecutar.

Proyecto personal desarrollado por **Pablo Oñate** (~3.100 líneas de Python).

## Cómo funciona

```
Micrófono ─► Palabra clave ("Hey Jarvis") ─► Voz a texto ─► Cerebro (LLM + herramientas) ─► Acciones
             openWakeWord (local)            faster-whisper   Claude API / Gemini             PC · Android · Alexa
                                             (local, GPU)          │                          Telegram · Rutinas
                                                                   └─► Respuesta por voz (edge-tts)
```

1. **Escucha local:** detecta "Hey Jarvis" sin internet con openWakeWord y transcribe con faster-whisper (en GPU si hay una NVIDIA).
2. **Cerebro:** un LLM (Claude por defecto, Gemini como alternativa) recibe la orden y llama herramientas mediante *tool use*, en un ciclo de hasta 8 pasos por petición.
3. **Acciones:** ejecuta las herramientas y responde por voz.

## Funcionalidades

- **PC:** abrir y cerrar programas y webs, volumen, multimedia, capturas, estado del sistema, bloquear o apagar.
- **Android (ADB por Wi-Fi):** batería, volumen, no molestar, abrir apps, brillo, Wi-Fi y Bluetooth.
- **Alexa (Voice Monkey):** anuncios en voz alta y disparo de rutinas (luces, enchufes, TV).
- **Telegram:** controlar a Jarvis desde el celular, en casa o fuera.
- **Rutinas en YAML:** secuencias de acciones ("modo trabajo", "buenas noches") que se activan por voz o a una hora programada.
- **Memoria y recordatorios** persistentes.
- **Siempre disponible:** arranca con Windows, un proceso vigilante lo reinicia si falla (con *backoff* exponencial) y tiene un ícono en la bandeja con su estado.

## Seguridad

- El panel y la API local solo escuchan en `127.0.0.1` y rechazan peticiones de otros orígenes; admiten token opcional.
- El bot de Telegram solo responde a IDs autorizados.
- Las acciones sensibles (apagar, reiniciar, comandos propios) piden confirmación.
- Las claves viven en `config.yaml`, que está fuera del repositorio (`.gitignore`); se incluye `config.example.yaml` como plantilla.

## Tecnologías

Python · API de Claude (Anthropic) · API de Gemini · faster-whisper · openWakeWord · edge-tts · python-telegram-bot · ADB · Voice Monkey · YAML · scripts .bat para Windows

## Estructura

```
Jarvis/
├── jarvis/
│   ├── brain.py         # Cerebro: proveedores LLM intercambiables y ciclo de tool use
│   ├── persona.py       # Prompt de sistema y personalidad
│   ├── memory.py        # Memoria y recordatorios
│   ├── servicio.py      # Vigilante: arranque automático y reinicio ante fallas
│   ├── tools/           # Herramientas: pc.py, phone.py, alexa.py, general.py
│   ├── voice/           # listener.py (palabra clave), stt.py, tts.py
│   └── interfaces/      # Telegram, panel HUD, ícono de bandeja
├── config.example.yaml  # Plantilla de configuración
├── rutinas.example.yaml # Rutinas de ejemplo
└── *.bat                # Instalar, iniciar, detener, probar
```

## Instalación

Requiere Windows 10/11. Ver la guía detallada en [`Jarvis/README.md`](Jarvis/README.md).

1. `instalar.bat`: instala dependencias y crea `config.yaml` desde la plantilla.
2. Pega tu clave de Claude o Gemini en `config.yaml`.
3. `probar.bat` para el diagnóstico e `iniciar.bat` para encenderlo.
