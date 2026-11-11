"""Brazilian Portuguese interface text, keyed by the English source text.

"Você" throughout. RPCS3 menu names (Manage > RPCN > RPCN Account,
Utilities > Decrypt PS3 Binaries, ...) stay in English because RPCS3's own
interface is English. Check with scripts/i18n_messages.py.
"""

MESSAGES = {
    "  Use the app instead: {app}":
        "  Use o aplicativo: {app}",
    " or ": " ou ",
    "A purchased Ludus slot (IDs 80002-80007) cannot be removed while the server is running. It is a purchased entitlement that the server replays at login. Stop the server and remove it offline instead.":
        "Uma vaga de Ludus comprada (IDs 80002-80007) não pode ser removida com o servidor em execução. É uma compra que o servidor reaplica no login. Pare o servidor e remova-a offline.",
    "Activity": "Atividade",
    "Add item": "Adicionar item",
    "Added item {item}. Press Save to write it to the save files.":
        "Item {item} adicionado. Clique em Salvar para gravá-lo nos arquivos de save.",
    "Automatic decryption does not work for me - use a decrypted .elf instead (RPCS3 Utilities > Decrypt PS3 Binaries)":
        "A descriptografia automática não funciona para mim: usar um .elf descriptografado (no RPCS3: Utilities > Decrypt PS3 Binaries)",
    "Backup: {path}": "Backup: {path}",
    "Balance synced: {balances}": "Saldo sincronizado: {balances}",
    "Balances saved.": "Saldos salvos.",
    "Before stopping:\n1. Return to the Ludus (main menu) in the game.\n2. Wait about 20 seconds so the game's native autosave finishes.\n3. Close RPCS3 first, then stop the server.\n\nStopping now can lose your latest progress. The server is never restarted automatically.":
        "Antes de parar:\n1. Volte ao Ludus (menu principal) no jogo.\n2. Espere cerca de 20 segundos para o salvamento automático do jogo terminar.\n3. Feche o RPCS3 primeiro e depois pare o servidor.\n\nParar agora pode fazer você perder o progresso mais recente. O servidor nunca é reiniciado automaticamente.",
    "Boost quantity only": "Somente quantidade de Boost",
    "Boosts (60000-60063)": "Boosts (60000-60063)",
    "Boosts are IDs 60000-60063 and keep a use count (0-99). Ludus slots are 80002-80007.":
        "Os Boosts são os IDs 60000-60063 e têm um número de usos (0-99). As vagas de Ludus são 80002-80007.",
    "Browse...": "Procurar...",
    "Change language": "Mudar idioma",
    "Check": "Verificação",
    "Check again": "Verificar novamente",
    "Choose a backup. Every file is checked against its SHA-256 manifest before anything is written.":
        "Escolha um backup. Cada arquivo é conferido com seu manifesto SHA-256 antes de qualquer gravação.",
    "Choose your RPCS3 folder to begin.": "Escolha sua pasta do RPCS3 para começar.",
    "Choose your RPCS3 folder. The game, its version and its executable are found and checked automatically; then press Install / repair setup. You only need to do this once.":
        "Escolha sua pasta do RPCS3. O jogo, a versão e o executável são encontrados e verificados automaticamente; depois clique em Instalar / reparar configuração. Você só precisa fazer isso uma vez.",
    "Clear": "Limpar",
    "Close": "Fechar",
    "Close RPCS3 before installing the setup. RPCS3 rewrites its configuration when it closes, which would undo the change.":
        "Feche o RPCS3 antes de instalar a configuração. O RPCS3 regrava a configuração dele ao fechar, o que desfaria a alteração.",
    "Close RPCS3 first": "Feche o RPCS3 primeiro",
    "Compatibility patch active - the game is loading its saves":
        "Patch de compatibilidade ativo: o jogo está carregando os saves",
    "Compatibility patch enabled for {title_id} {version} in {path}":
        "Patch de compatibilidade ativado para {title_id} {version} em {path}",
    "Compatibility patch installed in {path}":
        "Patch de compatibilidade instalado em {path}",
    "Continuing in the console. Start it with {flag} to skip this question.":
        "Continuando no console. Inicie com {flag} para pular esta pergunta.",
    "Copied": "Copiado",
    "Copy details": "Copiar detalhes",
    "Could not check the executable: {error} Tick the option below to use a decrypted .elf instead.":
        "Não foi possível verificar o executável: {error} Marque a opção abaixo para usar um .elf descriptografado.",
    "Could not find RPCS3's patches and config folders in: {folder}\nChoose the folder containing rpcs3.exe.":
        "As pastas patches e config do RPCS3 não foram encontradas em: {folder}\nEscolha a pasta que contém o rpcs3.exe.",
    "Could not find Spartacus Legends in this RPCS3 folder. Install the USA release ({title_id}) and let RPCS3 list it before playing.":
        "Spartacus Legends não foi encontrado nesta pasta do RPCS3. Instale a versão dos EUA ({title_id}) e deixe o RPCS3 listá-la antes de jogar.",
    "Could not hash {path}: {error}": "Não foi possível calcular o hash de {path}: {error}",
    "Could not inspect the executable hash: {error}":
        "Não foi possível examinar o hash do executável: {error}",
    "Could not open the app: {error}": "Não foi possível abrir o aplicativo: {error}",
    "Could not read {path}: {error}": "Não foi possível ler {path}: {error}",
    "Could not record the game version: {error}":
        "Não foi possível salvar a versão do jogo: {error}",
    "Could not start the server program: {error}\nIf this is a packaged copy, make sure {server} is in the same folder as SpartacusLegendsServerGUI.exe.":
        "Não foi possível iniciar o programa do servidor: {error}\nSe esta for uma cópia empacotada, verifique se {server} está na mesma pasta que o SpartacusLegendsServerGUI.exe.",
    "Dark theme": "Tema escuro",
    "Decrypted EBOOT .elf": "EBOOT .elf descriptografado",
    "Decrypted executable not found: {path}":
        "Executável descriptografado não encontrado: {path}",
    "ELF files (*.elf *.ELF);;All files (*)":
        "Arquivos ELF (*.elf *.ELF);;Todos os arquivos (*)",
    "EXECUTABLE": "EXECUTÁVEL",
    "Edit": "Editar",
    "Error": "Erro",
    "Error: {error}": "Erro: {error}",
    "Everything else - the game, its version and its executable - is found from this folder.":
        "Todo o resto (o jogo, a versão e o executável) é encontrado a partir desta pasta.",
    "Executable hash {hash} is covered by the installed patches":
        "O hash do executável {hash} é coberto pelos patches instalados",
    "Experimental: live item edits are not live-proven yet. An added item or changed Boost quantity should appear at the next shop inventory request or at the next login's purchase replay.":
        "Experimental: a edição de itens ao vivo ainda não foi comprovada em jogo real. Um item adicionado ou uma quantidade de Boost alterada deve aparecer na próxima vez que o jogo pedir o inventário da loja ou quando as compras forem reaplicadas no próximo login.",
    "FAME": "FAMA",
    "Fame is offline-only on 01.00: no live fame update is known for that client. Stop the server and edit fame offline.":
        "Na 01.00 a fama só pode ser editada offline: não se conhece nenhuma forma de atualizá-la ao vivo nessa versão. Pare o servidor e edite a fama offline.",
    "Finding the game and checking its executable...":
        "Procurando o jogo e verificando o executável...",
    "GAME": "JOGO",
    "GAME VERSION": "VERSÃO DO JOGO",
    "GOLD": "OURO",
    "Game connected": "Jogo conectado",
    "Game connected. Do not stop the server while you are playing.":
        "Jogo conectado. Não pare o servidor enquanto estiver jogando.",
    "Game disconnected": "Jogo desconectado",
    "Game installed: {title_id} version {version}":
        "Jogo instalado: {title_id} versão {version}",
    "Game profile (1.bin): gold {gold:,}, silver {silver:,}, fame {fame:,}":
        "Perfil do jogo (1.bin): ouro {gold:,}, prata {silver:,}, fama {fame:,}",
    "Game profile (1.bin): not created yet (fresh player). Only the server economy file will be edited.":
        "Perfil do jogo (1.bin): ainda não criado (jogador novo). Somente o arquivo de economia do servidor será editado.",
    "Game version mismatch": "A versão do jogo não confere",
    "Game {version}": "Jogo {version}",
    "Game {version} keeps balances on the server only. They are sent to the game at login and after each fight. The game's own profile ({size}) is never changed by this editor.":
        "O jogo {version} guarda os saldos somente no servidor. Eles são enviados ao jogo no login e depois de cada luta. Este editor nunca altera o perfil do próprio jogo ({size}).",
    "Generate a patch for your dump?": "Gerar um patch para o seu dump?",
    "Generated a patch for {hash} (experimental). Report: {path}":
        "Patch gerado para {hash} (experimental). Relatório: {path}",
    "Gold, silver and fame for your gladiator school.":
        "Ouro, prata e fama da sua escola de gladiadores.",
    "ITEM ID": "ID DO ITEM",
    "Install / repair setup": "Instalar / reparar configuração",
    "Install and verify the RPCS3 patch and network settings.":
        "Instale e verifique o patch e as configurações de rede do RPCS3.",
    "Install failed": "Falha na instalação",
    "Install failed: {error}": "Falha na instalação: {error}",
    "Install failed; nothing was guessed.":
        "Falha na instalação; nada foi presumido.",
    "Install or repair the setup, then cold-boot the game again.":
        "Instale ou repare a configuração e depois faça uma inicialização a frio do jogo.",
    "Installed the patches in {path}": "Patches instalados em {path}",
    "Installed, but the WARNING items can still stop the game from reaching the main menu.":
        "Instalado, mas os itens com AVISO ainda podem impedir que o jogo chegue ao menu principal.",
    "Installing the setup...": "Instalando a configuração...",
    "Is this the right RPCS3 folder?": "Esta é a pasta certa do RPCS3?",
    "Item ID": "ID do item",
    "Item ID to add, for example 60006 for a Boost.":
        "ID do item a adicionar; por exemplo, 60006 para um Boost.",
    "Item not added": "Item não adicionado",
    "Item not removed": "Item não removido",
    "Item {item} - Boost with {uses} use(s).": "Item {item}: Boost com {uses} uso(s).",
    "Item {item} - purchased Ludus slot entitlement.":
        "Item {item}: vaga de Ludus comprada.",
    "Item {item}.": "Item {item}.",
    "Items": "Itens",
    "Items are grouped by ID range only; no item names are asserted.":
        "Os itens são agrupados apenas por faixa de ID; nenhum nome de item é informado.",
    "Items saved. Pre-edit backup: {path}":
        "Itens salvos. Backup anterior à edição: {path}",
    "LAST BOOT": "ÚLTIMA INICIALIZAÇÃO",
    "Language": "Idioma",
    "Last boot: the compatibility patch was applied to {hash} ({writes} writes).":
        "Última inicialização: o patch de compatibilidade foi aplicado a {hash} ({writes} gravações).",
    "Last boot: {hash} started WITHOUT the compatibility patch.":
        "Última inicialização: {hash} foi iniciado SEM o patch de compatibilidade.",
    "Last saved: {value:,}": "Último salvo: {value:,}",
    "Leave the server's version unchanged": "Não alterar a versão do servidor",
    "Light theme": "Tema claro",
    "Live editing": "Edição ao vivo",
    "Live editing (experimental)": "Edição ao vivo (experimental)",
    "Live items from the server.": "Itens ao vivo do servidor.",
    "Live items from the server: {count} owned item(s).":
        "Itens ao vivo do servidor: {count} item(ns) possuído(s).",
    "Live values from the server.": "Valores ao vivo do servidor.",
    "Loaded {count} owned item(s) from the save files.":
        "{count} item(ns) possuído(s) carregado(s) dos arquivos de save.",
    "Logged in as {name}": "Login feito como {name}",
    "Ludus slot cannot be removed live":
        "A vaga de Ludus não pode ser removida ao vivo",
    "Ludus slots (80002-80007)": "Vagas de Ludus (80002-80007)",
    "MISSING": "FALTANDO",
    "Native profile: could not be read.": "Perfil nativo: não foi possível ler.",
    "Network setting {key}: {value}": "Configuração de rede {key}: {value}",
    "No EBOOT.BIN was found in {folder}.": "Nenhum EBOOT.BIN foi encontrado em {folder}.",
    "No RPCN account is set up in RPCS3 yet. Create one in RPCS3 under Manage > RPCN > RPCN Account before starting the game.":
        "Ainda não há nenhuma conta RPCN configurada no RPCS3. Crie uma no RPCS3, em Manage > RPCN > RPCN Account, antes de iniciar o jogo.",
    "No Spartacus Legends boot in RPCS3's log yet.":
        "Ainda não há nenhuma inicialização de Spartacus Legends no log do RPCS3.",
    "No backups": "Nenhum backup",
    "No decrypted executable supplied; hash coverage not checked":
        "Nenhum executável descriptografado informado; a cobertura do hash não foi verificada",
    "No item selected": "Nenhum item selecionado",
    "No item selected.": "Nenhum item selecionado.",
    "Nothing was changed.": "Nada foi alterado.",
    "Nothing was changed. Could not write to: {folders}.":
        "Nada foi alterado. Não foi possível gravar em: {folders}.",
    "Nothing yet - events appear here once the server starts.":
        "Nada ainda: os eventos aparecem aqui quando o servidor iniciar.",
    "OK": "OK",
    "Offline editing": "Edição offline",
    "Open logs folder": "Abrir pasta de logs",
    "Opening the app. This window can be closed.":
        "Abrindo o aplicativo. Você pode fechar esta janela.",
    "Other IDs": "Outros IDs",
    "Owned items": "Itens possuídos",
    "Owned items, Boost uses and purchased Ludus slots.":
        "Itens possuídos, usos de Boost e vagas de Ludus compradas.",
    "PPU cache cleared": "Cache PPU limpo",
    "PPU cache was already clear": "O cache PPU já estava limpo",
    "Patch setup": "Configurar patch",
    "Pending - appears after your next fight or shop purchase":
        "Pendente: aparece depois da sua próxima luta ou compra na loja",
    "Pending - appears after your next fight, shop purchase or login":
        "Pendente: aparece depois da sua próxima luta, compra na loja ou login",
    "Plain-language events from the server. The full protocol trace is always written to the logs folder.":
        "Eventos do servidor em linguagem simples. O registro completo do protocolo é sempre gravado na pasta de logs.",
    "Player": "Jogador",
    "Pre-edit backup: {path}": "Backup anterior à edição: {path}",
    "Press Enter to open the app (recommended), or type C and press Enter\nto keep using this console: ":
        "Pressione Enter para abrir o aplicativo (recomendado), ou digite C e pressione Enter\npara continuar usando este console: ",
    "Progress NOT saved ({name}): the game is version {game} but the server is set to {server}. Close RPCS3, stop the server, and run Patch setup again (or start the server with --title-version {game}).":
        "Progresso NÃO salvo ({name}): o jogo é a versão {game}, mas o servidor está configurado para {server}. Feche o RPCS3, pare o servidor e execute Configurar patch novamente (ou inicie o servidor com --title-version {game}).",
    "Progress NOT saved ({name}): {reason}.": "Progresso NÃO salvo ({name}): {reason}.",
    "Progress saved ({name})": "Progresso salvo ({name})",
    "Quantity is editable for Boost IDs 60000-60063 only.":
        "A quantidade só pode ser editada nos Boosts (IDs 60000-60063).",
    "Quantity not set": "Quantidade não alterada",
    "RPCN account configured": "Conta RPCN configurada",
    "RPCN has no account name saved. Create or sign in to an RPCN account in RPCS3 under Manage > RPCN > RPCN Account before starting the game.":
        "O RPCN não tem nenhum nome de conta salvo. Crie uma conta RPCN ou entre nela no RPCS3, em Manage > RPCN > RPCN Account, antes de iniciar o jogo.",
    "RPCS3 Bind address is {address}. The default loopback server cannot be reached from a bound game socket. Either clear Bind address for a normal single-client setup, or start SpartacusLegendsServer.exe with --host 0.0.0.0 --advertise-host <server-LAN-IP>. The advertised host is the server address RPCS3 can reach, not RPCS3's Bind address.":
        "O Bind address do RPCS3 é {address}. Um socket do jogo vinculado a esse endereço não alcança o servidor local padrão. Deixe o Bind address vazio para uma configuração normal de um só cliente, ou inicie o SpartacusLegendsServer.exe com --host 0.0.0.0 --advertise-host <IP-da-LAN-do-servidor>. O host anunciado é o endereço do servidor que o RPCS3 consegue alcançar, não o Bind address do RPCS3.",
    "RPCS3 has game version {detected}, but the server is set to {selected}. Saves from the other version are refused, so progress would not be kept.\n\nSwitch the server to {detected}?\n\nEach version keeps its own saves.":
        "O RPCS3 tem a versão {detected} do jogo, mas o servidor está configurado para {selected}. Os saves da outra versão são recusados, então o progresso não seria mantido.\n\nMudar o servidor para {detected}?\n\nCada versão mantém seus próprios saves.",
    "RPCS3 is open and keeps its log locked, so the last boot cannot be read yet. Close RPCS3, then check again.":
        "O RPCS3 está aberto e mantém o log bloqueado, então a última inicialização ainda não pode ser lida. Feche o RPCS3 e verifique novamente.",
    "RPCS3 is open. Its rpcs3.exe cannot decrypt a copy of the game's executable while another RPCS3 is running - close RPCS3, then check again.":
        "O RPCS3 está aberto. O rpcs3.exe dele não consegue descriptografar uma cópia do executável do jogo enquanto outro RPCS3 estiver em execução: feche o RPCS3 e verifique novamente.",
    "RPCS3's log has a Spartacus Legends boot but no executable hash line yet.":
        "O log do RPCS3 tem uma inicialização de Spartacus Legends, mas ainda não tem a linha com o hash do executável.",
    "Ready": "Pronto",
    "Reload from disk": "Recarregar do disco",
    "Reload live items": "Recarregar itens ao vivo",
    "Reload live values": "Recarregar valores ao vivo",
    "Remove a purchased Ludus slot?": "Remover uma vaga de Ludus comprada?",
    "Remove selected": "Remover selecionado",
    "Removed item {item}. Press Save to write it to the save files.":
        "Item {item} removido. Clique em Salvar para gravar nos arquivos de save.",
    "Replace the current save files with the backup {name}?\n\nThe current files are not backed up again by this step.":
        "Substituir os arquivos de save atuais pelo backup {name}?\n\nEsta etapa não faz um novo backup dos arquivos atuais.",
    "Restart the app now to use the new language?":
        "Reiniciar o aplicativo agora para usar o novo idioma?",
    "Restore backup": "Restaurar backup",
    "Restore backup...": "Restaurar backup...",
    "Restore complete": "Restauração concluída",
    "Restore refused": "Restauração recusada",
    "Restore this backup?": "Restaurar este backup?",
    "Restored: {files}": "Restaurado: {files}",
    "Result": "Resultado",
    "SELECTED": "SELECIONADO",
    "SILVER": "PRATA",
    "Save complete": "Salvamento concluído",
    "Save items to save files": "Salvar itens nos arquivos de save",
    "Save refused": "Salvamento recusado",
    "Save restored ({name})": "Save restaurado ({name})",
    "Save to save files": "Salvar nos arquivos de save",
    "Saved: {value:,}": "Salvo: {value:,}",
    "Select an item under one of the ranges first.":
        "Primeiro selecione um item dentro de uma das faixas.",
    "Select the RPCS3 folder (containing rpcs3.exe)":
        "Selecione a pasta do RPCS3 (a que contém o rpcs3.exe)",
    "Select the decrypted EBOOT .elf": "Selecione o EBOOT .elf descriptografado",
    "Send to server": "Enviar ao servidor",
    "Sent live add of item {item} (experimental).":
        "Enviado ao vivo: adicionar o item {item} (experimental).",
    "Sent live quantity {quantity} for item {item} (experimental).":
        "Enviada ao vivo a quantidade {quantity} para o item {item} (experimental).",
    "Sent live removal of item {item} (experimental).":
        "Enviado ao vivo: remover o item {item} (experimental).",
    "Server": "Servidor",
    "Server configured for game version {version} in {path}":
        "Servidor configurado para a versão {version} do jogo em {path}",
    "Server economy ({file}): gold {gold:,}, silver {silver:,}, fame {fame:,}":
        "Economia do servidor ({file}): ouro {gold:,}, prata {silver:,}, fama {fame:,}",
    "Server economy file: could not be read.":
        "Arquivo de economia do servidor: não foi possível ler.",
    "Server is configured for game version {configured}, but RPCS3 has {version}: {path}":
        "O servidor está configurado para a versão {configured} do jogo, mas o RPCS3 tem a {version}: {path}",
    "Server ready - start the game in RPCS3":
        "Servidor pronto: inicie o jogo no RPCS3",
    "Server ready - start the game in RPCS3 and log in.":
        "Servidor pronto: inicie o jogo no RPCS3 e faça login.",
    "Server set to game version {version}":
        "Servidor configurado para a versão {version} do jogo",
    "Server version configuration is missing: {path}":
        "A configuração de versão do servidor está faltando: {path}",
    "Server version left unchanged in {path}":
        "A versão do servidor não foi alterada em {path}",
    "Server v{version}": "Servidor v{version}",
    "Set Boost uses": "Definir usos do Boost",
    "Set item {item} quantity to {quantity}. Press Save to write it to the save files.":
        "Quantidade do item {item} definida como {quantity}. Clique em Salvar para gravar nos arquivos de save.",
    "Setup OK - start the server, then cold-boot the game.":
        "Configuração OK: inicie o servidor e depois faça uma inicialização a frio do jogo.",
    "Setup checklist": "Lista de verificação",
    "Setup incomplete - press Install / repair setup.":
        "Configuração incompleta: clique em Instalar / reparar configuração.",
    "Shop purchase: item {item}": "Compra na loja: item {item}",
    "Show detailed log": "Mostrar log detalhado",
    "Some files may have been changed; each changed file has a dated .bak copy beside it.":
        "Alguns arquivos podem ter sido alterados; cada arquivo alterado tem ao lado uma cópia .bak com data.",
    "Spartacus Legends was not found in {folder}. Install the USA release ({title_id}) in this RPCS3 and let RPCS3 list it, then check again.":
        "Spartacus Legends não foi encontrado em {folder}. Instale a versão dos EUA ({title_id}) neste RPCS3, deixe o RPCS3 listá-la e verifique novamente.",
    "Start server": "Iniciar servidor",
    "Start the server and follow what the game is doing.":
        "Inicie o servidor e acompanhe o que o jogo está fazendo.",
    "Starting": "Iniciando",
    "Starting the server...": "Iniciando o servidor...",
    "Stop server": "Parar servidor",
    "Stop the server while the game is connected?":
        "Parar o servidor com o jogo conectado?",
    "Stopped": "Parado",
    "Stopping": "Parando",
    "Stopping the server...": "Parando o servidor...",
    "Synced - the game has received these values":
        "Sincronizado: o jogo recebeu estes valores",
    "The RPCS3 folder - the one containing rpcs3.exe":
        "A pasta do RPCS3 (a que contém o rpcs3.exe)",
    "The compatibility patch did not take effect":
        "O patch de compatibilidade não teve efeito",
    "The game installed here is {found}, not {title_id}. Only the USA release is supported.":
        "O jogo instalado aqui é {found}, não {title_id}. Somente a versão dos EUA é suportada.",
    "The game is still connected to the server.":
        "O jogo ainda está conectado ao servidor.",
    "The game logged in but did not start loading its saves - the compatibility patch is not active.":
        "O jogo fez login, mas não começou a carregar os saves: o patch de compatibilidade não está ativo.",
    "The game logged in but never started loading its saves, so RPCS3 did not apply the patch. Close RPCS3, press Check again to read its last boot, then Install / repair setup and cold-boot.":
        "O jogo fez login, mas nunca começou a carregar os saves, então o RPCS3 não aplicou o patch. Feche o RPCS3, clique em Verificar novamente para ler a última inicialização, depois em Instalar / reparar configuração, e faça uma inicialização a frio.",
    "The game profile and server economy agree.":
        "O perfil do jogo e a economia do servidor conferem.",
    "The game profile and server economy differ ({fields}). Saving writes both so they agree.":
        "O perfil do jogo e a economia do servidor são diferentes ({fields}). Ao salvar, os dois são gravados para ficarem iguais.",
    "The game profile and server economy differ ({fields}). The running server uses its own in-memory values.":
        "O perfil do jogo e a economia do servidor são diferentes ({fields}). O servidor em execução usa os próprios valores em memória.",
    "The game reaches these through RPCS3's IP swap.":
        "O jogo chega a eles pelo IP swap do RPCS3.",
    "The game version could not be detected, so the server version in {path} was left as {version}. Choose the version you play when installing.":
        "Não foi possível detectar a versão do jogo, então a versão do servidor em {path} ficou como {version}. Escolha a versão que você joga ao instalar.",
    "The game version is not set and your saves do not show which one you have. Run Patch setup in SpartacusLegendsServerGUI.exe, or SpartacusLegendsPatchInstaller.exe, or start the server with --title-version 01.00 or --title-version 01.06. The server does not guess: the wrong version puts saves in the wrong folder.":
        "A versão do jogo não está configurada e seus saves não mostram qual você tem. Execute Configurar patch no SpartacusLegendsServerGUI.exe, ou o SpartacusLegendsPatchInstaller.exe, ou inicie o servidor com --title-version 01.00 ou --title-version 01.06. O servidor não adivinha: com a versão errada, os saves vão para a pasta errada.",
    "The game's version could not be detected from this RPCS3 folder, so the server's version setting will not be guessed. It decides which saves the server uses.\n\nWhich version of Spartacus Legends do you play?":
        "Não foi possível detectar a versão do jogo nesta pasta do RPCS3, então a versão do servidor não será adivinhada. Ela decide quais saves o servidor usa.\n\nQual versão de Spartacus Legends você joga?",
    "The install stopped part-way: {error}. These files could not be put back and still hold the new settings (their backups sit beside them): {files}":
        "A instalação parou no meio: {error}. Estes arquivos não puderam ser restaurados e ainda têm as novas configurações (os backups estão ao lado deles): {files}",
    "The install stopped: {error}. Every file it had already changed was put back, so nothing was changed.":
        "A instalação parou: {error}. Todos os arquivos que ela já tinha alterado foram restaurados, então nada foi alterado.",
    "The installed game is version {version}. Only {supported} are supported, so the patch will not apply. Either update to 01.06 or remove the game's update data (Manage > Title Database, or delete dev_hdd0/game/{title_id}-UPDATE) and reinstall the base game.":
        "O jogo instalado é a versão {version}. Somente {supported} são suportadas, então o patch não será aplicado. Atualize para 01.06, ou remova os dados de atualização do jogo (Manage > Title Database, ou apague dev_hdd0/game/{title_id}-UPDATE) e reinstale o jogo base.",
    "The last saved game profile and server economy agree.":
        "O último perfil do jogo salvo e a economia do servidor conferem.",
    "The native profile (1.bin) does not exist yet, so only the companion profile was edited. The game's next native autosave will create it.":
        "O perfil nativo (1.bin) ainda não existe, então somente o perfil complementar foi editado. O próximo salvamento automático do jogo vai criá-lo.",
    "The new language is used the next time you open the app. The server keeps running.":
        "O novo idioma será usado na próxima vez que você abrir o aplicativo. O servidor continua em execução.",
    "The save format stores a 32-bit value; this field accepts up to {maximum:,}.":
        "O formato do save guarda um valor de 32 bits; este campo aceita até {maximum:,}.",
    "The server could not start": "Não foi possível iniciar o servidor",
    "The server could not start, or stopped unexpectedly. Turn on the detailed log for the last error.":
        "Não foi possível iniciar o servidor, ou ele parou inesperadamente. Ative o log detalhado para ver o último erro.",
    "The server could not tell, and the wrong version puts your saves in the wrong folder. Choose your RPCS3 folder and press Install / repair setup, then start the server.":
        "O servidor não conseguiu identificar, e com a versão errada seus saves vão para a pasta errada. Escolha sua pasta do RPCS3, clique em Instalar / reparar configuração e depois inicie o servidor.",
    "The server did not stop within {seconds} seconds; terminating it now.":
        "O servidor não parou em {seconds} segundos; ele será encerrado à força agora.",
    "The server exited unexpectedly with code {code}. Open the detailed log or the logs folder for the full trace.":
        "O servidor fechou inesperadamente com o código {code}. Abra o log detalhado ou a pasta de logs para ver todos os detalhes.",
    "The server is not running. Choose your game version and press Start.":
        "O servidor não está em execução. Escolha a versão do seu jogo e clique em Iniciar servidor.",
    "The server is running, so gold and silver are changed through the server itself. The game picks them up at its next fight or shop purchase.":
        "O servidor está em execução, então o ouro e a prata são alterados pelo próprio servidor. O jogo os recebe na próxima luta ou compra na loja.",
    "The server is running, so gold, silver and fame are changed through the server itself. The game picks them up at its next fight, shop purchase or login.":
        "O servidor está em execução, então o ouro, a prata e a fama são alterados pelo próprio servidor. O jogo os recebe na próxima luta, compra na loja ou login.",
    "The server is running, so item edits go through the server. Saving to the save files is disabled while the server owns them.":
        "O servidor está em execução, então as edições de itens passam pelo servidor. Salvar nos arquivos de save fica desativado enquanto o servidor os usa.",
    "The server is still running": "O servidor ainda está em execução",
    "The server is still running. Stop it and close the window?\n\nIf the game is connected: return to the Ludus, wait about 20 seconds for the native autosave, then close RPCS3 first.":
        "O servidor ainda está em execução. Pará-lo e fechar a janela?\n\nSe o jogo estiver conectado: volte ao Ludus, espere cerca de 20 segundos pelo salvamento automático do jogo e feche o RPCS3 primeiro.",
    "The server is stopped, so the save files are edited directly. They are backed up before anything is changed.":
        "O servidor está parado, então os arquivos de save são editados diretamente. É feito um backup antes de qualquer alteração.",
    "The server is stopped. Changes are written only when you press Save, after the save files are backed up.":
        "O servidor está parado. As alterações só são gravadas quando você clica em Salvar, depois do backup dos arquivos de save.",
    "The server reported this problem. If another program is using port 80, the report below names it and suggests a fix.":
        "O servidor informou este problema. Se outro programa estiver usando a porta 80, o relatório abaixo mostra qual é e sugere uma solução.",
    "There are no save-editor backups in data/backups yet.":
        "Ainda não há backups do editor em data/backups.",
    "This RPCS3 folder has probably never been used to play Spartacus Legends: it has neither the game (NPUB30746) nor an RPCN account. Choose the RPCS3 you actually play from - in that RPCS3, right-click Spartacus Legends and choose Open Install Folder, then go up until you reach the folder that contains rpcs3.exe. Nothing was installed here.":
        "Esta pasta do RPCS3 provavelmente nunca foi usada para jogar Spartacus Legends: ela não tem nem o jogo (NPUB30746) nem uma conta RPCN. Escolha o RPCS3 em que você realmente joga: nesse RPCS3, clique com o botão direito em Spartacus Legends, escolha Open Install Folder e suba de pasta até chegar à que contém o rpcs3.exe. Nada foi instalado aqui.",
    "This dump cannot be patched automatically":
        "Este dump não pode receber o patch automaticamente",
    "This is a purchased Ludus slot entitlement (IDs 80002-80007). Removing it changes your purchased Ludus capacity: the server replays only the saved slot purchases at login. Remove it?":
        "Esta é uma vaga de Ludus comprada (IDs 80002-80007). Removê-la muda a capacidade do seu Ludus: no login, o servidor reaplica somente as compras de vagas salvas. Remover?",
    "This program is running at Windows' Low integrity level, so Windows blocks it from changing RPCS3's settings and your saves even though the folders allow it. That happens when the folder it was started from has a Low integrity label - some sandboxing tools add one to folders they work in. Copy the whole release folder somewhere ordinary (for example your Desktop or Documents) and start it from there.":
        "Este programa está rodando no nível de integridade Baixo do Windows, então o Windows o impede de alterar as configurações do RPCS3 e seus saves, mesmo que as pastas permitam. Isso acontece quando a pasta de onde ele foi iniciado tem um rótulo de integridade Baixo; algumas ferramentas de isolamento (sandbox) adicionam esse rótulo às pastas com que trabalham. Copie a pasta inteira do programa para um lugar comum (por exemplo, a Área de Trabalho ou Documentos) e inicie-o de lá.",
    "UDP port {port} on {host} is already in use ({error}). A Spartacus Legends server appears to be running outside this window (for example SpartacusLegendsServer.exe in a console). Stop it first: its in-memory economy would overwrite these edits. If another program holds the port, close that program instead.":
        "A porta UDP {port} em {host} já está em uso ({error}). Parece que há um servidor de Spartacus Legends em execução fora desta janela (por exemplo, o SpartacusLegendsServer.exe em um console). Pare-o primeiro: a economia em memória dele sobrescreveria estas edições. Se for outro programa usando a porta, feche esse programa.",
    "USES": "USOS",
    "Unknown title": "Título desconhecido",
    "Uses": "Usos",
    "Verification failed: {error}": "Falha na verificação: {error}",
    "WARNING": "AVISO",
    "Welcome - set up RPCS3 first": "Boas-vindas: primeiro configure o RPCS3",
    "Where these values are stored": "Onde estes valores ficam guardados",
    "Which game version?": "Qual versão do jogo?",
    "Which version of the game do you have?": "Qual versão do jogo você tem?",
    "Windows is limiting this copy of the program":
        "O Windows está limitando esta cópia do programa",
    "Windows refused to let this program create files there, although the folder's own permissions may allow it. Common causes: the program was started from a sandboxed terminal or tool (start it by double-clicking it in File Explorer instead), security software blocking an unrecognised program (allow it), or a folder that needs administrator rights (run it as administrator once).":
        "O Windows não deixou este programa criar arquivos ali, embora as permissões da pasta talvez permitam. Causas comuns: o programa foi iniciado a partir de um terminal ou ferramenta isolada (inicie-o com um clique duplo no Explorador de Arquivos), um software de segurança bloqueando um programa desconhecido (permita-o) ou uma pasta que exige direitos de administrador (execute-o como administrador uma vez).",
    "Your executable hash {hash} is not covered by the installed patches, so RPCS3 applies none of them. Run the installer again: it generates a matching patch for a different dump automatically (experimental).":
        "O hash do seu executável {hash} não é coberto pelos patches instalados, então o RPCS3 não aplica nenhum deles. Execute a instalação novamente: ela gera automaticamente um patch correspondente para outro dump (experimental).",
    "Your executable hash {hash} is not covered by the installed patches. The dump differs from the supported executables, so RPCS3 applies none of the patches. Run the installer with --adaptive --eboot-elf <decrypted .elf> to locate the patch sites by signature (experimental).":
        "O hash do seu executável {hash} não é coberto pelos patches instalados. O dump é diferente dos executáveis suportados, então o RPCS3 não aplica nenhum dos patches. Execute o instalador com --adaptive --eboot-elf <.elf descriptografado> para localizar os pontos do patch por assinatura (experimental).",
    "Your game": "Seu jogo",
    "Your game is a different dump of Spartacus Legends, so the shipped patch does not match its executable ({hash}).\n\nThe installer can generate a matching patch by locating the same instructions in your executable. This is EXPERIMENTAL: every patch site was found exactly once and checked, but it has only been proven on one other dump so far. Nothing is written if any site is uncertain.\n\nGenerate and install the patch for this dump?":
        "Seu jogo é um dump diferente de Spartacus Legends, então o patch incluído não corresponde ao executável dele ({hash}).\n\nO instalador pode gerar um patch correspondente localizando as mesmas instruções no seu executável. Isto é EXPERIMENTAL: cada ponto do patch foi encontrado exatamente uma vez e verificado, mas até agora só foi comprovado em um outro dump. Nada é gravado se algum ponto for incerto.\n\nGerar e instalar o patch para este dump?",
    "Your game's executable is a different dump and the patch sites could not be located safely:\n\n{problem}\n\nThe network settings can still be installed, but the compatibility patch will not apply to this executable. Continue anyway?":
        "O executável do seu jogo é um dump diferente e os pontos do patch não puderam ser localizados com segurança:\n\n{problem}\n\nAs configurações de rede ainda podem ser instaladas, mas o patch de compatibilidade não será aplicado a este executável. Continuar mesmo assim?",
    "an item ID must be a whole number":
        "o ID de um item deve ser um número inteiro",
    "an item ID must be a whole number, not {value!r}":
        "o ID de um item deve ser um número inteiro, não {value!r}",
    "an item quantity must be a whole number":
        "a quantidade de um item deve ser um número inteiro",
    "an item quantity must be a whole number, not {value!r}":
        "a quantidade de um item deve ser um número inteiro, não {value!r}",
    "another version": "outra versão",
    "campaign": "campanha",
    "could not read {path}: {error}": "não foi possível ler {path}: {error}",
    "edit save files": "editar os arquivos de save",
    "edited": "editado",
    "existing companion value": "valor complementar existente",
    "fame": "fama",
    "gold": "ouro",
    "item ID {item} does not fit in 32 bits":
        "o ID de item {item} não cabe em 32 bits",
    "item quantity must be between 0 and {maximum}":
        "a quantidade do item deve estar entre 0 e {maximum}",
    "item {item} is not owned": "o item {item} não é possuído",
    "item {item} is not owned; add it first":
        "o item {item} não é possuído; adicione-o primeiro",
    "no title ID": "sem ID de título",
    "not created yet": "ainda não criado",
    "not set": "não configurada",
    "only 01.00 and 01.06 are supported, so the patch will not apply.":
        "somente 01.00 e 01.06 são suportadas, então o patch não será aplicado.",
    "profile": "perfil",
    "refusing to edit save files while the server is running. Stop the server, return to the Ludus, wait about 20 seconds, and close RPCS3 first. Live edits use the server's control channel instead.":
        "os arquivos de save não são editados com o servidor em execução. Pare o servidor: volte ao Ludus, espere cerca de 20 segundos e feche o RPCS3 primeiro. As edições ao vivo usam o canal de controle do servidor.",
    "refusing to restore a backup while the server is running. Stop the server and close RPCS3 first.":
        "um backup não é restaurado com o servidor em execução. Pare o servidor e feche o RPCS3 primeiro.",
    "refusing to {action}: {reason}": "não é possível {action}: {reason}",
    "restore a backup": "restaurar um backup",
    "roster": "elenco",
    "silver": "prata",
    "the game folder {path} has no USRDIR/EBOOT.BIN":
        "a pasta do jogo {path} não tem USRDIR/EBOOT.BIN",
    "unknown": "desconhecida",
    "unknown error": "erro desconhecido",
    "{amount} fame": "{amount} de fama",
    "{amount} gold": "{amount} de ouro",
    "{amount} silver": "{amount} de prata",
    "{hash} - a different dump that cannot be patched automatically: {problem}":
        "{hash}: um dump diferente que não pode receber o patch automaticamente: {problem}",
    "{hash} - a different dump. A patch generated for it is installed (experimental).":
        "{hash}: um dump diferente. Um patch gerado para ele está instalado (experimental).",
    "{hash} - a different dump. Installing will generate a matching patch for it (experimental).":
        "{hash}: um dump diferente. A instalação vai gerar um patch correspondente para ele (experimental).",
    "{hash} - the supported {version} executable. The shipped patch covers it.":
        "{hash}: o executável {version} suportado. O patch incluído o cobre.",
    "{item} is the recruitment-store refresh command, not an item":
        "{item} é o comando para atualizar a loja de recrutamento, não um item",
    "{name} ({title_id}) version {version}": "{name} ({title_id}) versão {version}",
    "{name} must be a whole number": "{name} deve ser um número inteiro",
    "{name} must be a whole number, not {value!r}":
        "{name} deve ser um número inteiro, não {value!r}",
    "{name} {number} ({source}) does not fit in 32 bits; clamped to {maximum}.":
        "{name} {number} ({source}) não cabe em 32 bits; foi limitado a {maximum}.",
    "{name} {number} ({source}) is negative; clamped to 0.":
        "{name} {number} ({source}) é negativo; foi limitado a 0.",
    "{name} {number} is above {threshold:,}. The game's on-screen display limit is unknown (hypothesis: large values may display incorrectly). The value was written unchanged.":
        "{name} {number} passa de {threshold:,}. O limite que o jogo consegue mostrar na tela é desconhecido (hipótese: valores grandes podem aparecer errado). O valor foi gravado sem alteração.",
    "{path} is not a decrypted ELF. Run RPCS3 Utilities > Decrypt PS3 Binaries and choose the produced .elf, then verify again.":
        "{path} não é um ELF descriptografado. Use no RPCS3 Utilities > Decrypt PS3 Binaries, escolha o .elf gerado e verifique novamente.",
    "{problem}\n\nInstalling here writes the patch and network settings into this RPCS3 only - the RPCS3 you play from would still be unpatched (on 01.06 the game then hangs on \"Updating Game Data\").\n\nInstall into this folder anyway?":
        "{problem}\n\nInstalar aqui grava o patch e as configurações de rede somente neste RPCS3; o RPCS3 em que você joga continuaria sem o patch (na 01.06 o jogo então trava em \"Updating Game Data\").\n\nInstalar nesta pasta mesmo assim?",
    "{program} is the console version, for advanced and scripted use.\nThe app in this folder runs the same server, and it also sets up RPCS3,\nkeeps the game version right, shows when your progress is saved,\nand edits gold, fame and items.":
        "{program} é a versão de console, para uso avançado e com scripts.\nO aplicativo nesta pasta roda o mesmo servidor e também configura o RPCS3,\nmantém a versão do jogo correta, mostra quando seu progresso é salvo\ne edita ouro, fama e itens.",
    "{size:,} bytes": "{size:,} bytes",
}
