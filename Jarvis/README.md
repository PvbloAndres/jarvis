# J.A.R.V.I.S. — asistente personal con IA

Jarvis corre en tu PC con Windows y controla el PC, tu OnePlus 15 y Alexa con una sola voz.
**Se enciende solo cada vez que inicias sesión en Windows**, sin ventanas, y se vuelve a encender solo si algo falla.

## Arranque rápido

1. Doble clic en `instalar.bat` (instala todo, descarga los modelos de voz y activa el arranque con Windows).
2. Abre `config.yaml` con el Bloc de notas y pega tu clave de IA:
   - Claude (recomendado): https://console.anthropic.com → API Keys → `claude_api_key`
   - o Gemini (gratis con límites): https://aistudio.google.com/apikey → `gemini_api_key` y `proveedor: "gemini"`
3. Doble clic en `probar.bat`: revisa cerebro, micrófono, voz, GPU, teléfono, Alexa, Telegram y arranque automático.
4. Doble clic en `iniciar.bat` y di **"Hey Jarvis"**. Desde ahora, al encender el PC Jarvis despierta solo.

## Archivos

| Archivo | Para qué sirve |
| --- | --- |
| `instalar.bat` | Instala Python, dependencias, modelos de voz y el arranque automático |
| `iniciar.bat` | Enciende a Jarvis en segundo plano (ícono junto al reloj). `iniciar.bat ventana` lo abre con consola para ver errores |
| `detener.bat` | Apaga a Jarvis |
| `arranque-automatico.bat` | Activa o desactiva que Jarvis se encienda con Windows |
| `probar.bat` | Diagnóstico de cada pieza |
| `consola.bat` | Chatear por texto, sin voz (útil para probar) |
| `config.yaml` | Claves, voz, teléfono, Alexa, Telegram |
| `rutinas.yaml` | Tus rutinas ("modo trabajo", "buenas noches"...) |
| `orden.bat` | Envía una orden de texto a Jarvis (lo usa TRIGGERcmd para Alexa) |
| `triggercmd/commands.json` | Comandos para que Alexa le hable a Jarvis (instalar.bat pone la ruta correcta) |
| `data/` | Memoria, recordatorios y capturas (se respaldan con OneDrive) |

Fuera de OneDrive, en `%LOCALAPPDATA%\Jarvis`, quedan el entorno de Python (`venv`) y los registros (`logs\jarvis.log`,
`logs\vigilante.log`, `logs\consola.log`). Así OneDrive no sincroniza más de 1 GB de librerías ni un registro que cambia a cada rato.

## Siempre disponible

- **Arranca con Windows**: un acceso directo en la carpeta Inicio abre al *vigilante* (`jarvis.servicio`) 20 s después de iniciar sesión.
- **Se recupera solo**: si Jarvis se cae, el vigilante lo reinicia (esperando 5 s, 10 s, 20 s... hasta 5 min). Si falla por configuración (falta la clave, por ejemplo), muestra un aviso en pantalla en vez de reintentar sin fin.
- **Ícono junto al reloj**: el color indica el estado (celeste = en espera, verde = escuchando, ámbar = pensando, gris = micrófono en pausa). Clic derecho: abrir panel, pausar micrófono, ver registro, reiniciar o apagar.
- **Sin internet**: la palabra clave y Whisper funcionan sin conexión; si la voz en línea de Microsoft falla, habla con la voz de Windows (Sabina, español). Telegram se reconecta solo cuando vuelve internet.
- **Suspensión y audífonos**: al despertar el PC, o si cambias de micrófono, Jarvis vuelve a abrir el audio solo.
- **GPU NVIDIA**: si hay tarjeta (tu RTX 3060 Ti), Whisper usa `large-v3-turbo` en la GPU: entiende mucho mejor y responde más rápido. Sin GPU usa `small` en el procesador.
- **Una sola instancia**: abrir `iniciar.bat` con Jarvis ya encendido solo abre el panel.

## Encender el PC a distancia (opcional)

Jarvis vive en el PC, así que no puede encenderlo si está apagado. Opciones, de más a menos cómoda:

1. **Suspender en vez de apagar.** Di "Jarvis, suspende el PC". Al despertar (tecla, mouse o botón) Jarvis ya está listo al instante.
2. **Wake-on-LAN por cable** (tu placa Gigabyte H470 AORUS PRO AX lo soporta). Requiere conectar el PC por **cable Ethernet**: por Wi-Fi no funciona con el PC apagado.
   - BIOS (tecla Supr al encender): *Settings → Platform Power → ErP* = **Disabled** (Wake on LAN viene activado de fábrica en esta placa; si ves la opción, déjala en Enabled).
   - Windows: Administrador de dispositivos → *Intel Ethernet Controller I225-V* → Propiedades → *Administración de energía*: marca "Permitir que este dispositivo reactive el equipo" y "Solo paquete mágico". En *Opciones avanzadas*, "Wake on Magic Packet" = Habilitado.
   - Recomendado: desactiva el *Inicio rápido* (Panel de control → Opciones de energía → Elegir el comportamiento de los botones).
   - Luego enciéndelo desde el OnePlus con una app de Wake-on-LAN (misma red Wi-Fi) usando la dirección MAC del puerto Ethernet del PC.
3. **Enchufe inteligente + Alexa.** En la BIOS pon *AC BACK* = **Always On**; así el PC se enciende cuando vuelve la corriente. "Alexa, enciende el computador" activa el enchufe. Úsalo solo para encender: apaga siempre el PC desde Windows o con Jarvis antes de cortar el enchufe.

Para que Jarvis funcione apenas enciendes, Windows debe iniciar sesión. Si tienes contraseña o PIN, Jarvis arranca después de que entres.

## Qué puede hacer

- **PC:** abrir/cerrar programas, webs y búsquedas, volumen, música, bloquear, apagar/reiniciar (pide confirmación), ajustes de Windows, modo oscuro, brillo (notebooks), capturas, estado del sistema, comandos propios.
- **OnePlus 15 (ADB por Wi-Fi):** batería, volumen, no molestar, abrir apps y ajustes, brillo, Wi-Fi, Bluetooth, ahorro de batería, pantalla, capturas, abrir enlaces.
- **Alexa (Voice Monkey):** anuncios en voz alta y rutinas (luces, enchufes, TV...).
- **General:** clima, búsqueda web, recordatorios, memoria, rutinas programadas, mensajes por Telegram.

## Seguridad

- El panel y la API solo escuchan en `127.0.0.1` (tu propio PC) y rechazan peticiones de otras webs.
- El bot de Telegram solo obedece a los IDs de `usuarios_permitidos`.
- Apagar, reiniciar, comandos propios y apagar el Wi-Fi del teléfono siempre piden confirmación.
- No compartas `config.yaml`: contiene tus claves.
