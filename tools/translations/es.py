"""Spanish interface text, keyed by the English source text.

Informal "tú", as in most games. RPCS3 menu names (Manage > RPCN > RPCN
Account, Utilities > Decrypt PS3 Binaries, ...) stay in English because
RPCS3's own interface is English. Check with scripts/i18n_messages.py.
"""

MESSAGES = {
    "  Use the app instead: {app}":
        "  Usa la aplicación: {app}",
    " or ": " o ",
    "A purchased Ludus slot (IDs 80002-80007) cannot be removed while the server is running. It is a purchased entitlement that the server replays at login. Stop the server and remove it offline instead.":
        "Un espacio de Ludus comprado (ID 80002-80007) no se puede quitar mientras el servidor está en marcha. Es una compra que el servidor vuelve a aplicar al iniciar sesión. Detén el servidor y quítalo sin conexión.",
    "Activity": "Actividad",
    "Add item": "Añadir objeto",
    "Added item {item}. Press Save to write it to the save files.":
        "Objeto {item} añadido. Pulsa Guardar para escribirlo en los archivos de guardado.",
    "Automatic decryption does not work for me - use a decrypted .elf instead (RPCS3 Utilities > Decrypt PS3 Binaries)":
        "El descifrado automático no me funciona: usar un .elf descifrado (en RPCS3: Utilities > Decrypt PS3 Binaries)",
    "Backup: {path}": "Copia de seguridad: {path}",
    "Balance synced: {balances}": "Saldo sincronizado: {balances}",
    "Balances saved.": "Saldos guardados.",
    "Before stopping:\n1. Return to the Ludus (main menu) in the game.\n2. Wait about 20 seconds so the game's native autosave finishes.\n3. Close RPCS3 first, then stop the server.\n\nStopping now can lose your latest progress. The server is never restarted automatically.":
        "Antes de detenerlo:\n1. Vuelve al Ludus (menú principal) en el juego.\n2. Espera unos 20 segundos a que termine el autoguardado del juego.\n3. Cierra primero RPCS3 y después detén el servidor.\n\nSi lo detienes ahora, puedes perder tu progreso más reciente. El servidor nunca se reinicia solo.",
    "Boost quantity only": "Solo cantidad de Boost",
    "Boosts (60000-60063)": "Boosts (60000-60063)",
    "Boosts are IDs 60000-60063 and keep a use count (0-99). Ludus slots are 80002-80007.":
        "Los Boosts son los ID 60000-60063 y tienen un número de usos (0-99). Los espacios de Ludus son 80002-80007.",
    "Browse...": "Examinar...",
    "Change language": "Cambiar idioma",
    "Check": "Comprobación",
    "Check again": "Comprobar de nuevo",
    "Choose a backup. Every file is checked against its SHA-256 manifest before anything is written.":
        "Elige una copia de seguridad. Cada archivo se comprueba con su manifiesto SHA-256 antes de escribir nada.",
    "Choose your RPCS3 folder to begin.": "Elige tu carpeta de RPCS3 para empezar.",
    "Choose your RPCS3 folder. The game, its version and its executable are found and checked automatically; then press Install / repair setup. You only need to do this once.":
        "Elige tu carpeta de RPCS3. El juego, su versión y su ejecutable se encuentran y comprueban automáticamente; después pulsa Instalar / reparar configuración. Solo tienes que hacerlo una vez.",
    "Clear": "Borrar",
    "Close": "Cerrar",
    "Close RPCS3 before installing the setup. RPCS3 rewrites its configuration when it closes, which would undo the change.":
        "Cierra RPCS3 antes de instalar la configuración. RPCS3 reescribe su configuración al cerrarse, lo que desharía el cambio.",
    "Close RPCS3 first": "Cierra RPCS3 primero",
    "Compatibility patch active - the game is loading its saves":
        "Parche de compatibilidad activo: el juego está cargando sus partidas",
    "Compatibility patch enabled for {title_id} {version} in {path}":
        "Parche de compatibilidad activado para {title_id} {version} en {path}",
    "Compatibility patch installed in {path}":
        "Parche de compatibilidad instalado en {path}",
    "Continuing in the console. Start it with {flag} to skip this question.":
        "Se continúa en la consola. Inícialo con {flag} para saltarte esta pregunta.",
    "Copied": "Copiado",
    "Copy details": "Copiar detalles",
    "Could not check the executable: {error} Tick the option below to use a decrypted .elf instead.":
        "No se pudo comprobar el ejecutable: {error} Marca la opción de abajo para usar un .elf descifrado.",
    "Could not find RPCS3's patches and config folders in: {folder}\nChoose the folder containing rpcs3.exe.":
        "No se encontraron las carpetas patches y config de RPCS3 en: {folder}\nElige la carpeta que contiene rpcs3.exe.",
    "Could not find Spartacus Legends in this RPCS3 folder. Install the USA release ({title_id}) and let RPCS3 list it before playing.":
        "No se encontró Spartacus Legends en esta carpeta de RPCS3. Instala la versión de EE. UU. ({title_id}) y deja que RPCS3 la muestre en su lista antes de jugar.",
    "Could not hash {path}: {error}": "No se pudo calcular el hash de {path}: {error}",
    "Could not inspect the executable hash: {error}":
        "No se pudo examinar el hash del ejecutable: {error}",
    "Could not open the app: {error}": "No se pudo abrir la aplicación: {error}",
    "Could not read {path}: {error}": "No se pudo leer {path}: {error}",
    "Could not record the game version: {error}":
        "No se pudo guardar la versión del juego: {error}",
    "Could not start the server program: {error}\nIf this is a packaged copy, make sure {server} is in the same folder as SpartacusLegendsServerGUI.exe.":
        "No se pudo iniciar el programa del servidor: {error}\nSi es una copia empaquetada, asegúrate de que {server} está en la misma carpeta que SpartacusLegendsServerGUI.exe.",
    "Dark theme": "Tema oscuro",
    "Decrypted EBOOT .elf": "EBOOT .elf descifrado",
    "Decrypted executable not found: {path}":
        "No se encontró el ejecutable descifrado: {path}",
    "ELF files (*.elf *.ELF);;All files (*)":
        "Archivos ELF (*.elf *.ELF);;Todos los archivos (*)",
    "EXECUTABLE": "EJECUTABLE",
    "Edit": "Editar",
    "Error": "Error",
    "Error: {error}": "Error: {error}",
    "Everything else - the game, its version and its executable - is found from this folder.":
        "Todo lo demás (el juego, su versión y su ejecutable) se encuentra a partir de esta carpeta.",
    "Executable hash {hash} is covered by the installed patches":
        "El hash del ejecutable {hash} está cubierto por los parches instalados",
    "Experimental: live item edits are not live-proven yet. An added item or changed Boost quantity should appear at the next shop inventory request or at the next login's purchase replay.":
        "Experimental: la edición de objetos en directo aún no se ha probado en una partida real. Un objeto añadido o una cantidad de Boost cambiada debería aparecer la próxima vez que el juego pida el inventario de la tienda o al volver a aplicar las compras en el próximo inicio de sesión.",
    "FAME": "FAMA",
    "Fame is offline-only on 01.00: no live fame update is known for that client. Stop the server and edit fame offline.":
        "En 01.00 la fama solo se edita sin conexión: no se conoce ninguna forma de actualizarla en directo en esa versión. Detén el servidor y edita la fama sin conexión.",
    "Finding the game and checking its executable...":
        "Buscando el juego y comprobando su ejecutable...",
    "GAME": "JUEGO",
    "GAME VERSION": "VERSIÓN DEL JUEGO",
    "GOLD": "ORO",
    "Game connected": "Juego conectado",
    "Game connected. Do not stop the server while you are playing.":
        "Juego conectado. No detengas el servidor mientras juegas.",
    "Game disconnected": "Juego desconectado",
    "Game installed: {title_id} version {version}":
        "Juego instalado: {title_id} versión {version}",
    "Game profile (1.bin): gold {gold:,}, silver {silver:,}, fame {fame:,}":
        "Perfil del juego (1.bin): oro {gold:,}, plata {silver:,}, fama {fame:,}",
    "Game profile (1.bin): not created yet (fresh player). Only the server economy file will be edited.":
        "Perfil del juego (1.bin): aún no se ha creado (jugador nuevo). Solo se editará el archivo de economía del servidor.",
    "Game version mismatch": "La versión del juego no coincide",
    "Game {version}": "Juego {version}",
    "Game {version} keeps balances on the server only. They are sent to the game at login and after each fight. The game's own profile ({size}) is never changed by this editor.":
        "El juego {version} guarda los saldos solo en el servidor. Se envían al juego al iniciar sesión y después de cada combate. Este editor nunca modifica el perfil propio del juego ({size}).",
    "Generate a patch for your dump?": "¿Generar un parche para tu volcado?",
    "Generated a patch for {hash} (experimental). Report: {path}":
        "Se generó un parche para {hash} (experimental). Informe: {path}",
    "Gold, silver and fame for your gladiator school.":
        "Oro, plata y fama de tu escuela de gladiadores.",
    "ITEM ID": "ID DEL OBJETO",
    "Install / repair setup": "Instalar / reparar configuración",
    "Install and verify the RPCS3 patch and network settings.":
        "Instala y comprueba el parche y la configuración de red de RPCS3.",
    "Install failed": "La instalación falló",
    "Install failed: {error}": "La instalación falló: {error}",
    "Install failed; nothing was guessed.":
        "La instalación falló; no se supuso nada.",
    "Install or repair the setup, then cold-boot the game again.":
        "Instala o repara la configuración y vuelve a iniciar el juego en frío.",
    "Installed the patches in {path}": "Parches instalados en {path}",
    "Installed, but the WARNING items can still stop the game from reaching the main menu.":
        "Instalado, pero los elementos con AVISO todavía pueden impedir que el juego llegue al menú principal.",
    "Installing the setup...": "Instalando la configuración...",
    "Is this the right RPCS3 folder?": "¿Es esta la carpeta de RPCS3 correcta?",
    "Item ID": "ID del objeto",
    "Item ID to add, for example 60006 for a Boost.":
        "ID del objeto que se añadirá; por ejemplo, 60006 para un Boost.",
    "Item not added": "Objeto no añadido",
    "Item not removed": "Objeto no quitado",
    "Item {item} - Boost with {uses} use(s).": "Objeto {item}: Boost con {uses} uso(s).",
    "Item {item} - purchased Ludus slot entitlement.":
        "Objeto {item}: espacio de Ludus comprado.",
    "Item {item}.": "Objeto {item}.",
    "Items": "Objetos",
    "Items are grouped by ID range only; no item names are asserted.":
        "Los objetos se agrupan solo por rangos de ID; no se indican nombres de objetos.",
    "Items saved. Pre-edit backup: {path}":
        "Objetos guardados. Copia de seguridad previa: {path}",
    "LAST BOOT": "ÚLTIMO ARRANQUE",
    "Language": "Idioma",
    "Last boot: the compatibility patch was applied to {hash} ({writes} writes).":
        "Último arranque: el parche de compatibilidad se aplicó a {hash} ({writes} escrituras).",
    "Last boot: {hash} started WITHOUT the compatibility patch.":
        "Último arranque: {hash} se inició SIN el parche de compatibilidad.",
    "Last saved: {value:,}": "Último guardado: {value:,}",
    "Leave the server's version unchanged": "No cambiar la versión del servidor",
    "Light theme": "Tema claro",
    "Live editing": "Edición en directo",
    "Live editing (experimental)": "Edición en directo (experimental)",
    "Live items from the server.": "Objetos en directo del servidor.",
    "Live items from the server: {count} owned item(s).":
        "Objetos en directo del servidor: {count} objeto(s) en propiedad.",
    "Live values from the server.": "Valores en directo del servidor.",
    "Loaded {count} owned item(s) from the save files.":
        "Se cargaron {count} objeto(s) en propiedad de los archivos de guardado.",
    "Logged in as {name}": "Sesión iniciada como {name}",
    "Ludus slot cannot be removed live":
        "El espacio de Ludus no se puede quitar en directo",
    "Ludus slots (80002-80007)": "Espacios de Ludus (80002-80007)",
    "MISSING": "FALTA",
    "Native profile: could not be read.": "Perfil nativo: no se pudo leer.",
    "Network setting {key}: {value}": "Ajuste de red {key}: {value}",
    "No EBOOT.BIN was found in {folder}.": "No se encontró ningún EBOOT.BIN en {folder}.",
    "No RPCN account is set up in RPCS3 yet. Create one in RPCS3 under Manage > RPCN > RPCN Account before starting the game.":
        "Todavía no hay ninguna cuenta RPCN configurada en RPCS3. Crea una en RPCS3, en Manage > RPCN > RPCN Account, antes de iniciar el juego.",
    "No Spartacus Legends boot in RPCS3's log yet.":
        "Todavía no hay ningún arranque de Spartacus Legends en el registro de RPCS3.",
    "No backups": "No hay copias de seguridad",
    "No decrypted executable supplied; hash coverage not checked":
        "No se indicó ningún ejecutable descifrado; no se comprobó si el hash está cubierto",
    "No item selected": "Ningún objeto seleccionado",
    "No item selected.": "Ningún objeto seleccionado.",
    "Nothing was changed.": "No se cambió nada.",
    "Nothing was changed. Could not write to: {folders}.":
        "No se cambió nada. No se pudo escribir en: {folders}.",
    "Nothing yet - events appear here once the server starts.":
        "Nada todavía: los eventos aparecerán aquí cuando se inicie el servidor.",
    "OK": "OK",
    "Offline editing": "Edición sin conexión",
    "Open logs folder": "Abrir carpeta de registros",
    "Opening the app. This window can be closed.":
        "Abriendo la aplicación. Puedes cerrar esta ventana.",
    "Other IDs": "Otros ID",
    "Owned items": "Objetos en propiedad",
    "Owned items, Boost uses and purchased Ludus slots.":
        "Objetos en propiedad, usos de Boost y espacios de Ludus comprados.",
    "PPU cache cleared": "Caché PPU borrada",
    "PPU cache was already clear": "La caché PPU ya estaba vacía",
    "Patch setup": "Configurar parche",
    "Pending - appears after your next fight or shop purchase":
        "Pendiente: aparecerá después de tu próximo combate o compra en la tienda",
    "Pending - appears after your next fight, shop purchase or login":
        "Pendiente: aparecerá después de tu próximo combate, compra en la tienda o inicio de sesión",
    "Plain-language events from the server. The full protocol trace is always written to the logs folder.":
        "Eventos del servidor explicados de forma sencilla. El registro completo del protocolo siempre se guarda en la carpeta de registros.",
    "Player": "Jugador",
    "Pre-edit backup: {path}": "Copia de seguridad previa: {path}",
    "Press Enter to open the app (recommended), or type C and press Enter\nto keep using this console: ":
        "Pulsa Intro para abrir la aplicación (recomendado), o escribe C y pulsa Intro\npara seguir usando esta consola: ",
    "Progress NOT saved ({name}): the game is version {game} but the server is set to {server}. Close RPCS3, stop the server, and run Patch setup again (or start the server with --title-version {game}).":
        "Progreso NO guardado ({name}): el juego es la versión {game}, pero el servidor está configurado para {server}. Cierra RPCS3, detén el servidor y vuelve a ejecutar Configurar parche (o inicia el servidor con --title-version {game}).",
    "Progress NOT saved ({name}): {reason}.": "Progreso NO guardado ({name}): {reason}.",
    "Progress saved ({name})": "Progreso guardado ({name})",
    "Quantity is editable for Boost IDs 60000-60063 only.":
        "La cantidad solo se puede editar en los Boosts (ID 60000-60063).",
    "Quantity not set": "Cantidad no cambiada",
    "RPCN account configured": "Cuenta RPCN configurada",
    "RPCN has no account name saved. Create or sign in to an RPCN account in RPCS3 under Manage > RPCN > RPCN Account before starting the game.":
        "RPCN no tiene ningún nombre de cuenta guardado. Crea una cuenta RPCN o inicia sesión en RPCS3, en Manage > RPCN > RPCN Account, antes de iniciar el juego.",
    "RPCS3 Bind address is {address}. The default loopback server cannot be reached from a bound game socket. Either clear Bind address for a normal single-client setup, or start SpartacusLegendsServer.exe with --host 0.0.0.0 --advertise-host <server-LAN-IP>. The advertised host is the server address RPCS3 can reach, not RPCS3's Bind address.":
        "El Bind address de RPCS3 es {address}. Un socket del juego asociado a esa dirección no puede llegar al servidor local predeterminado. Deja vacío Bind address para una configuración normal de un solo cliente, o inicia SpartacusLegendsServer.exe con --host 0.0.0.0 --advertise-host <IP-LAN-del-servidor>. El host anunciado es la dirección del servidor a la que RPCS3 puede llegar, no el Bind address de RPCS3.",
    "RPCS3 has game version {detected}, but the server is set to {selected}. Saves from the other version are refused, so progress would not be kept.\n\nSwitch the server to {detected}?\n\nEach version keeps its own saves.":
        "RPCS3 tiene la versión {detected} del juego, pero el servidor está configurado para {selected}. Las partidas de la otra versión se rechazan, así que el progreso no se guardaría.\n\n¿Cambiar el servidor a {detected}?\n\nCada versión conserva sus propias partidas.",
    "RPCS3 is open and keeps its log locked, so the last boot cannot be read yet. Close RPCS3, then check again.":
        "RPCS3 está abierto y mantiene su registro bloqueado, así que todavía no se puede leer el último arranque. Cierra RPCS3 y vuelve a comprobar.",
    "RPCS3 is open. Its rpcs3.exe cannot decrypt a copy of the game's executable while another RPCS3 is running - close RPCS3, then check again.":
        "RPCS3 está abierto. Su rpcs3.exe no puede descifrar una copia del ejecutable del juego mientras otro RPCS3 está en marcha: cierra RPCS3 y vuelve a comprobar.",
    "RPCS3's log has a Spartacus Legends boot but no executable hash line yet.":
        "El registro de RPCS3 tiene un arranque de Spartacus Legends, pero todavía no tiene la línea con el hash del ejecutable.",
    "Ready": "Listo",
    "Reload from disk": "Recargar del disco",
    "Reload live items": "Recargar objetos en directo",
    "Reload live values": "Recargar valores en directo",
    "Remove a purchased Ludus slot?": "¿Quitar un espacio de Ludus comprado?",
    "Remove selected": "Quitar seleccionado",
    "Removed item {item}. Press Save to write it to the save files.":
        "Objeto {item} quitado. Pulsa Guardar para escribirlo en los archivos de guardado.",
    "Replace the current save files with the backup {name}?\n\nThe current files are not backed up again by this step.":
        "¿Sustituir los archivos de guardado actuales por la copia de seguridad {name}?\n\nEste paso no vuelve a hacer copia de seguridad de los archivos actuales.",
    "Restart the app now to use the new language?":
        "¿Reiniciar la aplicación ahora para usar el nuevo idioma?",
    "Restore backup": "Restaurar copia de seguridad",
    "Restore backup...": "Restaurar copia de seguridad...",
    "Restore complete": "Restauración completada",
    "Restore refused": "Restauración rechazada",
    "Restore this backup?": "¿Restaurar esta copia de seguridad?",
    "Restored: {files}": "Restaurado: {files}",
    "Result": "Resultado",
    "SELECTED": "SELECCIONADO",
    "SILVER": "PLATA",
    "Save complete": "Guardado completado",
    "Save items to save files": "Guardar objetos en los archivos de guardado",
    "Save refused": "Guardado rechazado",
    "Save restored ({name})": "Partida restaurada ({name})",
    "Save to save files": "Guardar en los archivos de guardado",
    "Saved: {value:,}": "Guardado: {value:,}",
    "Select an item under one of the ranges first.":
        "Primero selecciona un objeto dentro de uno de los rangos.",
    "Select the RPCS3 folder (containing rpcs3.exe)":
        "Selecciona la carpeta de RPCS3 (la que contiene rpcs3.exe)",
    "Select the decrypted EBOOT .elf": "Selecciona el EBOOT .elf descifrado",
    "Send to server": "Enviar al servidor",
    "Sent live add of item {item} (experimental).":
        "Enviado en directo: añadir el objeto {item} (experimental).",
    "Sent live quantity {quantity} for item {item} (experimental).":
        "Enviada en directo la cantidad {quantity} para el objeto {item} (experimental).",
    "Sent live removal of item {item} (experimental).":
        "Enviado en directo: quitar el objeto {item} (experimental).",
    "Server": "Servidor",
    "Server configured for game version {version} in {path}":
        "Servidor configurado para la versión {version} del juego en {path}",
    "Server economy ({file}): gold {gold:,}, silver {silver:,}, fame {fame:,}":
        "Economía del servidor ({file}): oro {gold:,}, plata {silver:,}, fama {fame:,}",
    "Server economy file: could not be read.":
        "Archivo de economía del servidor: no se pudo leer.",
    "Server is configured for game version {configured}, but RPCS3 has {version}: {path}":
        "El servidor está configurado para la versión {configured} del juego, pero RPCS3 tiene la {version}: {path}",
    "Server ready - start the game in RPCS3":
        "Servidor listo: inicia el juego en RPCS3",
    "Server ready - start the game in RPCS3 and log in.":
        "Servidor listo: inicia el juego en RPCS3 e inicia sesión.",
    "Server set to game version {version}":
        "Servidor configurado para la versión {version} del juego",
    "Server version configuration is missing: {path}":
        "Falta la configuración de versión del servidor: {path}",
    "Server version left unchanged in {path}":
        "La versión del servidor no se cambió en {path}",
    "Server v{version}": "Servidor v{version}",
    "Set Boost uses": "Cambiar usos del Boost",
    "Set item {item} quantity to {quantity}. Press Save to write it to the save files.":
        "Cantidad del objeto {item} cambiada a {quantity}. Pulsa Guardar para escribirla en los archivos de guardado.",
    "Setup OK - start the server, then cold-boot the game.":
        "Configuración correcta: inicia el servidor y después inicia el juego en frío.",
    "Setup checklist": "Lista de comprobación",
    "Setup incomplete - press Install / repair setup.":
        "Configuración incompleta: pulsa Instalar / reparar configuración.",
    "Shop purchase: item {item}": "Compra en la tienda: objeto {item}",
    "Show detailed log": "Mostrar registro detallado",
    "Some files may have been changed; each changed file has a dated .bak copy beside it.":
        "Puede que se hayan cambiado algunos archivos; cada archivo cambiado tiene al lado una copia .bak con fecha.",
    "Spartacus Legends was not found in {folder}. Install the USA release ({title_id}) in this RPCS3 and let RPCS3 list it, then check again.":
        "No se encontró Spartacus Legends en {folder}. Instala la versión de EE. UU. ({title_id}) en este RPCS3, deja que RPCS3 la muestre en su lista y vuelve a comprobar.",
    "Start server": "Iniciar servidor",
    "Start the server and follow what the game is doing.":
        "Inicia el servidor y sigue lo que hace el juego.",
    "Starting": "Iniciando",
    "Starting the server...": "Iniciando el servidor...",
    "Stop server": "Detener servidor",
    "Stop the server while the game is connected?":
        "¿Detener el servidor con el juego conectado?",
    "Stopped": "Detenido",
    "Stopping": "Deteniendo",
    "Stopping the server...": "Deteniendo el servidor...",
    "Synced - the game has received these values":
        "Sincronizado: el juego ha recibido estos valores",
    "The RPCS3 folder - the one containing rpcs3.exe":
        "La carpeta de RPCS3 (la que contiene rpcs3.exe)",
    "The compatibility patch did not take effect":
        "El parche de compatibilidad no se aplicó",
    "The game installed here is {found}, not {title_id}. Only the USA release is supported.":
        "El juego instalado aquí es {found}, no {title_id}. Solo se admite la versión de EE. UU.",
    "The game is still connected to the server.":
        "El juego sigue conectado al servidor.",
    "The game logged in but did not start loading its saves - the compatibility patch is not active.":
        "El juego inició sesión, pero no empezó a cargar sus partidas: el parche de compatibilidad no está activo.",
    "The game logged in but never started loading its saves, so RPCS3 did not apply the patch. Close RPCS3, press Check again to read its last boot, then Install / repair setup and cold-boot.":
        "El juego inició sesión, pero nunca empezó a cargar sus partidas, así que RPCS3 no aplicó el parche. Cierra RPCS3, pulsa Comprobar de nuevo para leer su último arranque, después Instalar / reparar configuración, e inicia el juego en frío.",
    "The game profile and server economy agree.":
        "El perfil del juego y la economía del servidor coinciden.",
    "The game profile and server economy differ ({fields}). Saving writes both so they agree.":
        "El perfil del juego y la economía del servidor no coinciden ({fields}). Al guardar se escriben los dos para que coincidan.",
    "The game profile and server economy differ ({fields}). The running server uses its own in-memory values.":
        "El perfil del juego y la economía del servidor no coinciden ({fields}). El servidor en marcha usa sus propios valores en memoria.",
    "The game reaches these through RPCS3's IP swap.":
        "El juego llega a ellos mediante el IP swap de RPCS3.",
    "The game version could not be detected, so the server version in {path} was left as {version}. Choose the version you play when installing.":
        "No se pudo detectar la versión del juego, así que la versión del servidor en {path} se dejó como {version}. Elige la versión a la que juegas al instalar.",
    "The game version is not set and your saves do not show which one you have. Run Patch setup in SpartacusLegendsServerGUI.exe, or SpartacusLegendsPatchInstaller.exe, or start the server with --title-version 01.00 or --title-version 01.06. The server does not guess: the wrong version puts saves in the wrong folder.":
        "La versión del juego no está configurada y tus partidas no indican cuál tienes. Ejecuta Configurar parche en SpartacusLegendsServerGUI.exe, o SpartacusLegendsPatchInstaller.exe, o inicia el servidor con --title-version 01.00 o --title-version 01.06. El servidor no adivina: con la versión equivocada, las partidas se guardan en la carpeta equivocada.",
    "The game's version could not be detected from this RPCS3 folder, so the server's version setting will not be guessed. It decides which saves the server uses.\n\nWhich version of Spartacus Legends do you play?":
        "No se pudo detectar la versión del juego en esta carpeta de RPCS3, así que la versión del servidor no se va a adivinar. Esa versión decide qué partidas usa el servidor.\n\n¿Qué versión de Spartacus Legends juegas?",
    "The install stopped part-way: {error}. These files could not be put back and still hold the new settings (their backups sit beside them): {files}":
        "La instalación se detuvo a medias: {error}. Estos archivos no se pudieron restaurar y todavía tienen la nueva configuración (sus copias de seguridad están al lado): {files}",
    "The install stopped: {error}. Every file it had already changed was put back, so nothing was changed.":
        "La instalación se detuvo: {error}. Todos los archivos que ya había cambiado se restauraron, así que no se cambió nada.",
    "The installed game is version {version}. Only {supported} are supported, so the patch will not apply. Either update to 01.06 or remove the game's update data (Manage > Title Database, or delete dev_hdd0/game/{title_id}-UPDATE) and reinstall the base game.":
        "El juego instalado es la versión {version}. Solo se admiten {supported}, así que el parche no se aplicará. Actualiza a 01.06, o elimina los datos de actualización del juego (Manage > Title Database, o borra dev_hdd0/game/{title_id}-UPDATE) y vuelve a instalar el juego base.",
    "The last saved game profile and server economy agree.":
        "El último perfil del juego guardado y la economía del servidor coinciden.",
    "The native profile (1.bin) does not exist yet, so only the companion profile was edited. The game's next native autosave will create it.":
        "El perfil nativo (1.bin) todavía no existe, así que solo se editó el perfil complementario. El próximo autoguardado del juego lo creará.",
    "The new language is used the next time you open the app. The server keeps running.":
        "El nuevo idioma se usará la próxima vez que abras la aplicación. El servidor sigue en marcha.",
    "The save format stores a 32-bit value; this field accepts up to {maximum:,}.":
        "El formato de guardado almacena un valor de 32 bits; este campo admite hasta {maximum:,}.",
    "The server could not start": "No se pudo iniciar el servidor",
    "The server could not start, or stopped unexpectedly. Turn on the detailed log for the last error.":
        "No se pudo iniciar el servidor o se detuvo de forma inesperada. Activa el registro detallado para ver el último error.",
    "The server could not tell, and the wrong version puts your saves in the wrong folder. Choose your RPCS3 folder and press Install / repair setup, then start the server.":
        "El servidor no pudo saberlo, y con la versión equivocada tus partidas se guardan en la carpeta equivocada. Elige tu carpeta de RPCS3, pulsa Instalar / reparar configuración y después inicia el servidor.",
    "The server did not stop within {seconds} seconds; terminating it now.":
        "El servidor no se detuvo en {seconds} segundos; se está cerrando a la fuerza.",
    "The server exited unexpectedly with code {code}. Open the detailed log or the logs folder for the full trace.":
        "El servidor se cerró de forma inesperada con el código {code}. Abre el registro detallado o la carpeta de registros para ver todo el detalle.",
    "The server is not running. Choose your game version and press Start.":
        "El servidor no está en marcha. Elige la versión de tu juego y pulsa Iniciar servidor.",
    "The server is running, so gold and silver are changed through the server itself. The game picks them up at its next fight or shop purchase.":
        "El servidor está en marcha, así que el oro y la plata se cambian a través del propio servidor. El juego los recibe en su próximo combate o compra en la tienda.",
    "The server is running, so gold, silver and fame are changed through the server itself. The game picks them up at its next fight, shop purchase or login.":
        "El servidor está en marcha, así que el oro, la plata y la fama se cambian a través del propio servidor. El juego los recibe en su próximo combate, compra en la tienda o inicio de sesión.",
    "The server is running, so item edits go through the server. Saving to the save files is disabled while the server owns them.":
        "El servidor está en marcha, así que los cambios de objetos pasan por el servidor. Guardar en los archivos de guardado está desactivado mientras el servidor los usa.",
    "The server is still running": "El servidor sigue en marcha",
    "The server is still running. Stop it and close the window?\n\nIf the game is connected: return to the Ludus, wait about 20 seconds for the native autosave, then close RPCS3 first.":
        "El servidor sigue en marcha. ¿Detenerlo y cerrar la ventana?\n\nSi el juego está conectado: vuelve al Ludus, espera unos 20 segundos al autoguardado del juego y cierra primero RPCS3.",
    "The server is stopped, so the save files are edited directly. They are backed up before anything is changed.":
        "El servidor está detenido, así que los archivos de guardado se editan directamente. Se hace una copia de seguridad antes de cambiar nada.",
    "The server is stopped. Changes are written only when you press Save, after the save files are backed up.":
        "El servidor está detenido. Los cambios solo se escriben al pulsar Guardar, después de hacer una copia de seguridad de los archivos de guardado.",
    "The server reported this problem. If another program is using port 80, the report below names it and suggests a fix.":
        "El servidor informó de este problema. Si otro programa está usando el puerto 80, el informe de abajo indica cuál es y propone una solución.",
    "There are no save-editor backups in data/backups yet.":
        "Todavía no hay copias de seguridad del editor en data/backups.",
    "This RPCS3 folder has probably never been used to play Spartacus Legends: it has neither the game (NPUB30746) nor an RPCN account. Choose the RPCS3 you actually play from - in that RPCS3, right-click Spartacus Legends and choose Open Install Folder, then go up until you reach the folder that contains rpcs3.exe. Nothing was installed here.":
        "Probablemente esta carpeta de RPCS3 nunca se ha usado para jugar a Spartacus Legends: no tiene ni el juego (NPUB30746) ni una cuenta RPCN. Elige el RPCS3 con el que juegas de verdad: en ese RPCS3, haz clic derecho en Spartacus Legends, elige Open Install Folder y sube de carpeta hasta llegar a la que contiene rpcs3.exe. No se instaló nada aquí.",
    "This dump cannot be patched automatically":
        "Este volcado no se puede parchear automáticamente",
    "This is a purchased Ludus slot entitlement (IDs 80002-80007). Removing it changes your purchased Ludus capacity: the server replays only the saved slot purchases at login. Remove it?":
        "Es un espacio de Ludus comprado (ID 80002-80007). Si lo quitas, cambia la capacidad de tu Ludus: al iniciar sesión, el servidor solo vuelve a aplicar las compras de espacios guardadas. ¿Quitarlo?",
    "This program is running at Windows' Low integrity level, so Windows blocks it from changing RPCS3's settings and your saves even though the folders allow it. That happens when the folder it was started from has a Low integrity label - some sandboxing tools add one to folders they work in. Copy the whole release folder somewhere ordinary (for example your Desktop or Documents) and start it from there.":
        "Este programa se está ejecutando con el nivel de integridad Bajo de Windows, así que Windows le impide cambiar la configuración de RPCS3 y tus partidas aunque las carpetas lo permitan. Ocurre cuando la carpeta desde la que se inició tiene una etiqueta de integridad Baja; algunas herramientas de aislamiento (sandbox) la añaden a las carpetas con las que trabajan. Copia la carpeta completa del programa a un lugar normal (por ejemplo, el Escritorio o Documentos) e inícialo desde allí.",
    "UDP port {port} on {host} is already in use ({error}). A Spartacus Legends server appears to be running outside this window (for example SpartacusLegendsServer.exe in a console). Stop it first: its in-memory economy would overwrite these edits. If another program holds the port, close that program instead.":
        "El puerto UDP {port} en {host} ya está en uso ({error}). Parece que hay un servidor de Spartacus Legends en marcha fuera de esta ventana (por ejemplo, SpartacusLegendsServer.exe en una consola). Detenlo primero: su economía en memoria sobrescribiría estos cambios. Si es otro programa el que usa el puerto, cierra ese programa.",
    "USES": "USOS",
    "Unknown title": "Título desconocido",
    "Uses": "Usos",
    "Verification failed: {error}": "La comprobación falló: {error}",
    "WARNING": "AVISO",
    "Welcome - set up RPCS3 first": "Te damos la bienvenida: primero configura RPCS3",
    "Where these values are stored": "Dónde se guardan estos valores",
    "Which game version?": "¿Qué versión del juego?",
    "Which version of the game do you have?": "¿Qué versión del juego tienes?",
    "Windows is limiting this copy of the program":
        "Windows está limitando esta copia del programa",
    "Windows refused to let this program create files there, although the folder's own permissions may allow it. Common causes: the program was started from a sandboxed terminal or tool (start it by double-clicking it in File Explorer instead), security software blocking an unrecognised program (allow it), or a folder that needs administrator rights (run it as administrator once).":
        "Windows no permitió que este programa creara archivos ahí, aunque los permisos de la carpeta quizá lo permitan. Causas habituales: el programa se inició desde un terminal o una herramienta aislada (inícialo con doble clic en el Explorador de archivos), un software de seguridad que bloquea un programa desconocido (permítelo) o una carpeta que necesita permisos de administrador (ejecútalo como administrador una vez).",
    "Your executable hash {hash} is not covered by the installed patches, so RPCS3 applies none of them. Run the installer again: it generates a matching patch for a different dump automatically (experimental).":
        "El hash de tu ejecutable {hash} no está cubierto por los parches instalados, así que RPCS3 no aplica ninguno. Vuelve a ejecutar la instalación: genera automáticamente un parche adecuado para otro volcado (experimental).",
    "Your executable hash {hash} is not covered by the installed patches. The dump differs from the supported executables, so RPCS3 applies none of the patches. Run the installer with --adaptive --eboot-elf <decrypted .elf> to locate the patch sites by signature (experimental).":
        "El hash de tu ejecutable {hash} no está cubierto por los parches instalados. El volcado es distinto de los ejecutables admitidos, así que RPCS3 no aplica ninguno de los parches. Ejecuta el instalador con --adaptive --eboot-elf <.elf descifrado> para localizar los puntos del parche por firma (experimental).",
    "Your game": "Tu juego",
    "Your game is a different dump of Spartacus Legends, so the shipped patch does not match its executable ({hash}).\n\nThe installer can generate a matching patch by locating the same instructions in your executable. This is EXPERIMENTAL: every patch site was found exactly once and checked, but it has only been proven on one other dump so far. Nothing is written if any site is uncertain.\n\nGenerate and install the patch for this dump?":
        "Tu juego es un volcado distinto de Spartacus Legends, así que el parche incluido no coincide con su ejecutable ({hash}).\n\nEl instalador puede generar un parche adecuado localizando las mismas instrucciones en tu ejecutable. Esto es EXPERIMENTAL: cada punto del parche se encontró exactamente una vez y se comprobó, pero de momento solo se ha probado en otro volcado. No se escribe nada si algún punto es dudoso.\n\n¿Generar e instalar el parche para este volcado?",
    "Your game's executable is a different dump and the patch sites could not be located safely:\n\n{problem}\n\nThe network settings can still be installed, but the compatibility patch will not apply to this executable. Continue anyway?":
        "El ejecutable de tu juego es un volcado distinto y no se pudieron localizar con seguridad los puntos del parche:\n\n{problem}\n\nLa configuración de red se puede instalar igualmente, pero el parche de compatibilidad no se aplicará a este ejecutable. ¿Continuar de todos modos?",
    "an item ID must be a whole number":
        "el ID de un objeto debe ser un número entero",
    "an item ID must be a whole number, not {value!r}":
        "el ID de un objeto debe ser un número entero, no {value!r}",
    "an item quantity must be a whole number":
        "la cantidad de un objeto debe ser un número entero",
    "an item quantity must be a whole number, not {value!r}":
        "la cantidad de un objeto debe ser un número entero, no {value!r}",
    "another version": "otra versión",
    "campaign": "campaña",
    "could not read {path}: {error}": "no se pudo leer {path}: {error}",
    "edit save files": "editar los archivos de guardado",
    "edited": "editado",
    "existing companion value": "valor complementario existente",
    "fame": "fama",
    "gold": "oro",
    "item ID {item} does not fit in 32 bits":
        "el ID de objeto {item} no cabe en 32 bits",
    "item quantity must be between 0 and {maximum}":
        "la cantidad del objeto debe estar entre 0 y {maximum}",
    "item {item} is not owned": "el objeto {item} no está en propiedad",
    "item {item} is not owned; add it first":
        "el objeto {item} no está en propiedad; añádelo primero",
    "no title ID": "sin ID de título",
    "not created yet": "aún no creado",
    "not set": "sin configurar",
    "only 01.00 and 01.06 are supported, so the patch will not apply.":
        "solo se admiten 01.00 y 01.06, así que el parche no se aplicará.",
    "profile": "perfil",
    "refusing to edit save files while the server is running. Stop the server, return to the Ludus, wait about 20 seconds, and close RPCS3 first. Live edits use the server's control channel instead.":
        "no se editan los archivos de guardado mientras el servidor está en marcha. Detén el servidor: vuelve al Ludus, espera unos 20 segundos y cierra primero RPCS3. Los cambios en directo usan el canal de control del servidor.",
    "refusing to restore a backup while the server is running. Stop the server and close RPCS3 first.":
        "no se restaura una copia de seguridad mientras el servidor está en marcha. Detén el servidor y cierra primero RPCS3.",
    "refusing to {action}: {reason}": "no se puede {action}: {reason}",
    "restore a backup": "restaurar una copia de seguridad",
    "roster": "plantel",
    "silver": "plata",
    "the game folder {path} has no USRDIR/EBOOT.BIN":
        "la carpeta del juego {path} no tiene USRDIR/EBOOT.BIN",
    "unknown": "desconocida",
    "unknown error": "error desconocido",
    "{amount} fame": "{amount} de fama",
    "{amount} gold": "{amount} de oro",
    "{amount} silver": "{amount} de plata",
    "{hash} - a different dump that cannot be patched automatically: {problem}":
        "{hash}: un volcado distinto que no se puede parchear automáticamente: {problem}",
    "{hash} - a different dump. A patch generated for it is installed (experimental).":
        "{hash}: un volcado distinto. Tiene instalado un parche generado para él (experimental).",
    "{hash} - a different dump. Installing will generate a matching patch for it (experimental).":
        "{hash}: un volcado distinto. Al instalar se generará un parche adecuado para él (experimental).",
    "{hash} - the supported {version} executable. The shipped patch covers it.":
        "{hash}: el ejecutable {version} admitido. El parche incluido lo cubre.",
    "{item} is the recruitment-store refresh command, not an item":
        "{item} es la orden de actualizar la tienda de reclutamiento, no un objeto",
    "{name} ({title_id}) version {version}": "{name} ({title_id}) versión {version}",
    "{name} must be a whole number": "{name} debe ser un número entero",
    "{name} must be a whole number, not {value!r}":
        "{name} debe ser un número entero, no {value!r}",
    "{name} {number} ({source}) does not fit in 32 bits; clamped to {maximum}.":
        "{name} {number} ({source}) no cabe en 32 bits; se limitó a {maximum}.",
    "{name} {number} ({source}) is negative; clamped to 0.":
        "{name} {number} ({source}) es negativo; se limitó a 0.",
    "{name} {number} is above {threshold:,}. The game's on-screen display limit is unknown (hypothesis: large values may display incorrectly). The value was written unchanged.":
        "{name} {number} supera {threshold:,}. Se desconoce el límite que el juego puede mostrar en pantalla (hipótesis: los valores grandes podrían verse mal). El valor se escribió sin cambios.",
    "{path} is not a decrypted ELF. Run RPCS3 Utilities > Decrypt PS3 Binaries and choose the produced .elf, then verify again.":
        "{path} no es un ELF descifrado. Usa en RPCS3 Utilities > Decrypt PS3 Binaries, elige el .elf generado y vuelve a comprobar.",
    "{problem}\n\nInstalling here writes the patch and network settings into this RPCS3 only - the RPCS3 you play from would still be unpatched (on 01.06 the game then hangs on \"Updating Game Data\").\n\nInstall into this folder anyway?":
        "{problem}\n\nSi instalas aquí, el parche y la configuración de red solo se escriben en este RPCS3; el RPCS3 con el que juegas seguiría sin parche (en 01.06 el juego se queda entonces en \"Updating Game Data\").\n\n¿Instalar en esta carpeta de todos modos?",
    "{program} is the console version, for advanced and scripted use.\nThe app in this folder runs the same server, and it also sets up RPCS3,\nkeeps the game version right, shows when your progress is saved,\nand edits gold, fame and items.":
        "{program} es la versión de consola, para uso avanzado y con scripts.\nLa aplicación de esta carpeta ejecuta el mismo servidor y además configura RPCS3,\nmantiene correcta la versión del juego, muestra cuándo se guarda tu progreso\ny edita el oro, la fama y los objetos.",
    "{size:,} bytes": "{size:,} bytes",
    "Purchase refused: the server's gold or silver does not cover {what}. Nothing was charged.":
        'Compra rechazada: el oro o la plata del servidor no alcanzan para {what}. No se cobró nada.',
    'a recruit refresh':
        'renovar los reclutas',
    'item {item}':
        'el objeto {item}',
    'gladiator {gladiator}':
        'el gladiador {gladiator}',
    'title {title}':
        'el título {title}',
}
