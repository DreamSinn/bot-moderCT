import discord
from discord.ext import commands
from discord import app_commands
import os
import json
from typing import Dict, List, Any
from pathlib import Path

# --- Configuração do Bot ---
# É crucial habilitar o "Message Content Intent" e o "Privileged Gateway Intents"
# no portal de desenvolvedores do Discord.
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.members = True # Necessário para algumas operações de cargo/membro

# O token foi inserido diretamente no código.
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)

# --- Funções de Gerenciamento de Presets ---
PRESET_FILE = str(Path(__file__).parent / "role_presets.json")

def load_presets() -> Dict[str, List[Dict[str, Any]]]:
    """Carrega os presets de cargos do arquivo JSON."""
    if not os.path.exists(PRESET_FILE):
        return {}
    try:
        with open(PRESET_FILE, 'r', encoding='utf-8') as f:
            # Tenta carregar o JSON. Se o arquivo estiver vazio, retorna um dicionário vazio.
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"ERRO: O arquivo {PRESET_FILE} está mal formatado ou vazio.")
        return {}
    except Exception as e:
        print(f"ERRO ao carregar presets: {e}")
        return {}

def save_presets(presets: Dict[str, List[Dict[str, Any]]]):
    """Salva os presets de cargos no arquivo JSON."""
    with open(PRESET_FILE, 'w', encoding='utf-8') as f:
        json.dump(presets, f, indent=4, ensure_ascii=False)

class ModerationBot(commands.Bot):
    def __init__(self, *, intents: discord.Intents):
        # Usamos um prefixo, mas o foco será nos comandos de barra
        super().__init__(command_prefix='!', intents=intents)
        # O self.tree já é inicializado pela classe base commands.Bot em versões recentes.
        # A linha abaixo foi removida para evitar o erro "ClientException: This client already has an associated command tree."
        # self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        """Confirma que o bot está conectado e sincroniza os comandos de barra."""
        print(f'Bot conectado como {self.user} (ID: {self.user.id})')
        
        # Sincroniza os comandos de barra (slash commands) com o Discord.
        # Isso pode levar alguns minutos para aparecer em grandes servidores.
        await self.tree.sync()
        print('Comandos de barra sincronizados.')
        
        # DEBUG: Imprime o caminho absoluto do arquivo de preset para ajudar na depuração
        print(f'DEBUG: O bot procurará o arquivo de presets em: {PRESET_FILE}')
        print('--------------------------------------------------')

    async def setup_hook(self):
        """Carrega as cogs (extensões) do bot."""
        # Carrega a cog de clonagem de servidor
        try:
            await self.load_extension('bot_cloner')
            print('Cog de clonagem (bot_cloner) carregada com sucesso.')
        except Exception as e:
            print(f'ERRO ao carregar a cog de clonagem: {e}')

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Tratamento de erros para comandos de barra."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                f"❌ Você não tem permissão para usar este comando. É necessária a permissão: `{', '.join(error.missing_permissions)}`.",
                ephemeral=True
            )
        elif isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Este comando está em cooldown. Tente novamente em {error.retry_after:.2f} segundos.",
                ephemeral=True
            )
        else:
            print(f"Erro inesperado no comando de barra: {error}")
            await interaction.response.send_message("❌ Ocorreu um erro inesperado ao executar o comando.", ephemeral=True)

bot = ModerationBot(intents=intents)

# --- Comando de Criação de Cargos (/criar_cargos) ---
# (Mantido para compatibilidade, mas a lógica será usada no preset)
@bot.tree.command(name='criar_cargos', description='Cria e ordena cargos no servidor a partir de uma lista de nomes.')
@app_commands.describe(lista_cargos='Lista de cargos separados por vírgula ou nova linha (do mais alto para o mais baixo).')
@app_commands.checks.has_permissions(manage_roles=True)
async def criar_cargos_slash(interaction: discord.Interaction, lista_cargos: str):
    """
    Cria e ordena cargos no servidor a partir de uma lista de nomes fornecida como argumento.
    Requer a permissão 'Gerenciar Cargos' (Manage Roles).
    """
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("Este comando só pode ser usado em um servidor.", ephemeral=True)
        return

    # 1. Parse the input
    # Substitui vírgulas por nova linha e filtra linhas vazias
    role_names = [name.strip() for name in lista_cargos.replace(',', '\n').split('\n') if name.strip()]
    
    if not role_names:
        await interaction.followup.send("Nenhum cargo válido foi fornecido.", ephemeral=True)
        return

    created_roles = []
    failed_roles = []
    
    # 2. Create the roles
    # Cria os cargos na ordem em que foram fornecidos
    for name in role_names:
        try:
            # Cria o cargo com permissões padrão (None)
            new_role = await guild.create_role(name=name, reason=f"Criação via /criar_cargos por {interaction.user.name}")
            created_roles.append(new_role)
        except discord.Forbidden:
            failed_roles.append(f"❌ {name} (Permissões insuficientes)")
            break # Se falhar por permissão, provavelmente falhará nos próximos
        except Exception as e:
            failed_roles.append(f"❌ {name} (Erro: {e})")

    # 3. Set the hierarchy (reordering)
    if created_roles:
        # A lista de cargos fornecida pelo usuário é do mais alto para o mais baixo.
        # O Discord ordena os cargos de baixo para cima (posição 0 é a mais baixa).
        
        reorder_success = True
        try:
            # Lista de todos os cargos do servidor, ordenada do mais baixo para o mais alto.
            roles_to_reorder = guild.roles
            
            # Encontra o índice do cargo mais alto do bot na lista ordenada.
            bot_role_index = roles_to_reorder.index(guild.me.top_role)
            
            # Remove os cargos recém-criados da lista `roles_to_reorder` para inseri-los
            # na posição correta.
            roles_to_reorder = [r for r in roles_to_reorder if r.id not in [r.id for r in created_roles]]
            
            # Inverte a lista de cargos criados para que o mais alto seja inserido primeiro
            # na posição mais alta (logo abaixo do bot).
            created_roles.reverse()
            
            # Posição de inserção: logo abaixo do cargo do bot.
            insert_position = bot_role_index
            
            # Insere os cargos na lista `roles_to_reorder` na ordem correta (do mais alto para o mais baixo)
            for role in created_roles:
                roles_to_reorder.insert(insert_position, role)
                insert_position -= 1 # Insere o próximo cargo abaixo do anterior
                     # Cria a lista de tuplas (role, position) para a API
            # A posição é o índice na lista `roles_to_reorder`.
            # Usando o formato de tuplas (role, position) para máxima compatibilidade.
            new_role_positions = [
                {'id': role.id, 'position': index}
                for index, role in enumerate(roles_to_reorder)
            ]
            
            await guild.edit_role_positions(new_role_positions, reason=f"Reordenação via /preset_cargos usar {nome} por {interaction.user.name}")    
        except discord.Forbidden:
            reorder_success = False
            failed_roles.append("❌ Reordenação (Permissões insuficientes para mover cargos)")
        except Exception as e:
            reorder_success = False
            failed_roles.append(f"❌ Reordenação (Erro: {e})")

    # 4. Send confirmation
    if created_roles:
        success_message = "✅ **Cargos Criados e Ordenados:**\n"
        success_message += "\n".join([f"✨ {role.name}" for role in created_roles])
        
        if failed_roles:
            success_message += "\n\n⚠️ **Avisos/Falhas:**\n"
            success_message += "\n".join(failed_roles)
            
        if not reorder_success and created_roles:
            success_message += "\n\n⚠️ **Atenção:** Os cargos foram criados, mas a reordenação falhou. Você precisará ajustá-la manualmente."
            
        await interaction.followup.send(success_message, ephemeral=False)
    else:
        await interaction.followup.send("❌ **Falha na Criação de Cargos:**\n" + "\n".join(failed_roles), ephemeral=True)


# --- Comando de Grupo de Presets (/preset_cargos) ---
preset_group = app_commands.Group(name='preset_cargos', description='Gerencia presets de cargos para criação rápida.')
bot.tree.add_command(preset_group)

@preset_group.command(name='listar', description='Lista todos os presets de cargos disponíveis.')
@app_commands.checks.has_permissions(manage_roles=True)
async def preset_listar_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    presets = load_presets()
    if not presets:
        await interaction.followup.send("❌ Nenhum preset de cargo encontrado.", ephemeral=True)
        return

    message = "✨ **Presets de Cargos Disponíveis:**\n"
    for name, role_data_list in presets.items():
        # Pega os nomes dos cargos para o exemplo
        role_names = [data.get('name', 'Cargo Desconhecido') for data in role_data_list]
        
        message += f"**- {name.upper()}** ({len(role_names)} cargos)\n"
        message += f"  *Exemplo: {', '.join(role_names[:3])}...*\n"
        
    await interaction.followup.send(message, ephemeral=True)
@preset_group.command(name='salvar', description='Salva uma lista de cargos como um novo preset.')
@app_commands.describe(nome='Nome único para o preset.', lista_cargos='Lista de cargos separados por vírgula ou nova linha (do mais alto para o mais baixo).')
@app_commands.checks.has_permissions(administrator=True)
async def preset_salvar_slash(interaction: discord.Interaction, nome: str, lista_cargos: str):
    await interaction.response.defer(ephemeral=True)
    
    # 1. Parse the input
    role_names = [name.strip() for name in lista_cargos.replace(',', '\n').split('\n') if name.strip()]
    
    if not role_names:
        await interaction.followup.send("Nenhum cargo válido foi fornecido para salvar.", ephemeral=True)
        return

    # Novo formato: Lista de dicionários com nome, permissão padrão (0) e cor padrão (#FFFFFF)
    # O usuário pode editar o JSON depois para adicionar as permissões e cores
    role_data_list = [{'name': name, 'permissions': 0, 'color': '#FFFFFF'} for name in role_names]

    presets = load_presets()
    presets[nome.lower()] = role_data_list
    save_presets(presets)
    
    await interaction.followup.send(f"✅ Preset **{nome.upper()}** salvo com sucesso com {len(role_names)} cargos (permissões padrão). Você pode editar o arquivo `role_presets.json` para definir as permissões.", ephemeral=True)
@preset_group.command(name='usar', description='Cria cargos no servidor a partir de um preset salvo.')
@app_commands.describe(nome='Nome do preset a ser usado.')
@app_commands.checks.has_permissions(manage_roles=True)
async def preset_usar_slash(interaction: discord.Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("Este comando só pode ser usado em um servidor.", ephemeral=True)
        return

    presets = load_presets()
    role_data_list = presets.get(nome.lower())
    
    if not role_data_list:
        await interaction.followup.send(f"❌ Preset **{nome.upper()}** não encontrado. Use `/preset_cargos listar` para ver os disponíveis.", ephemeral=True)
        return

    # Lógica de criação de cargos (reutilizada do /criar_cargos)
    created_roles = []
    failed_roles = []
    
    # 2. Create the roles
    for role_data in role_data_list:
            name = role_data.get('name')
            permissions_value = role_data.get('permissions', 0) # Padrão 0 se não houver permissão
            color_hex = role_data.get('color', '#FFFFFF') # Padrão branco se não houver cor
            
            if not name:
                continue

            try:
                # Cria o objeto Permissions a partir do valor inteiro
                perms = discord.Permissions(permissions=permissions_value)
                
                # VERIFICAÇÃO DE PERMISSÃO: O bot não pode criar um cargo com permissões que ele mesmo não tem.
                # O bot precisa ter a permissão de "Administrator" (8) para criar um cargo com "Administrator" (8).
                if perms.administrator and not guild.me.guild_permissions.administrator:
                    failed_roles.append(f"❌ {name} (O bot não tem permissão de Administrador para criar um cargo com Administrador)")
                    continue
                
                # Converte a cor hexadecimal para o formato do Discord (int)
                color_int = int(color_hex.lstrip('#'), 16)
                
                # Cria o cargo aplicando as permissões e a cor
                new_role = await guild.create_role(
                    name=name, 
                    permissions=perms, 
                    colour=discord.Colour(color_int),
                    reason=f"Criação via /preset_cargos usar {nome} por {interaction.user.name}"
                )
                created_roles.append(new_role)
            except discord.Forbidden:
                failed_roles.append(f"❌ {name} (Permissões insuficientes)")
                break
            except Exception as e:
                failed_roles.append(f"❌ {name} (Erro: {e})")

    # 3. Set the hierarchy (reordering)
    if created_roles:
        reorder_success = True
        try:
            roles_to_reorder = guild.roles
            bot_role_index = roles_to_reorder.index(guild.me.top_role)
            roles_to_reorder = [r for r in roles_to_reorder if r.id not in [r.id for r in created_roles]]
            created_roles.reverse()
            insert_position = bot_role_index
            for role in created_roles:
                # Insere cada cargo na posição correta (logo abaixo do cargo do bot), descendo a posição a cada inserção.
                roles_to_reorder.insert(insert_position, role)
                insert_position -= 1
            # A posição é o índice na lista `roles_to_reorder`.
            # Usando o formato de tuplas (role, position) para máxima compatibilidade.
            new_role_positions = [
                {'id': role.id, 'position': index}
                for index, role in enumerate(roles_to_reorder)
            ]
            
            await guild.edit_role_positions(new_role_positions, reason=f"Reordenação via /preset_cargos usar {nome} por {interaction.user.name}")           
        except discord.Forbidden:
            reorder_success = False
            failed_roles.append("❌ Reordenação (Permissões insuficientes para mover cargos)")
        except Exception as e:
            reorder_success = False
            failed_roles.append(f"❌ Reordenação (Erro: {e})")

    # 4. Send confirmation
    if created_roles:
        success_message = f"✅ **Preset {nome.upper()} Aplicado:**\n"
        success_message += "\n".join([f"✨ {role.name}" for role in created_roles])
        
        if failed_roles:
            success_message += "\n\n⚠️ **Avisos/Falhas:**\n"
            success_message += "\n".join(failed_roles)
            
        if not reorder_success and created_roles:
            success_message += "\n\n⚠️ **Atenção:** Os cargos foram criados, mas a reordenação falhou. Você precisará ajustá-la manualmente."
            
        await interaction.followup.send(success_message, ephemeral=False)
    else:
        await interaction.followup.send("❌ **Falha na Criação de Cargos:**\n" + "\n".join(failed_roles), ephemeral=True)


# --- Comando de Sincronização (/sync) ---
@bot.tree.command(name='sync', description='Sincroniza os comandos de barra com o Discord.')
@app_commands.checks.has_permissions(administrator=True)
async def sync_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await bot.tree.sync()
    await interaction.followup.send('✅ Comandos de barra sincronizados com sucesso!', ephemeral=True)

# --- Comando de Limpeza (/limpar) ---
@bot.tree.command(name='limpar', description='Apaga um número específico de mensagens no canal.')
@app_commands.describe(quantidade='O número de mensagens a apagar (máximo 100).')
@app_commands.checks.has_permissions(manage_messages=True)
async def limpar_slash(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100]):
    """
    Apaga as últimas 'quantidade' mensagens no canal onde o comando foi executado.
    Requer a permissão 'Gerenciar Mensagens' (Manage Messages).
    """
    await interaction.response.defer(ephemeral=True) # Deixa o bot pensando enquanto processa

    # Garante que a quantidade não é negativa (embora o Range já faça isso)
    if quantidade <= 0:
        await interaction.followup.send("A quantidade de mensagens a apagar deve ser um número positivo.", ephemeral=True)
        return

    try:
        # Adiciona 1 à quantidade para apagar a própria mensagem de comando (interação)
        # Nota: O comando de barra não gera uma mensagem de texto tradicional, mas a interação é a referência.
        # A função purge retorna uma lista das mensagens apagadas
        deleted = await interaction.channel.purge(limit=quantidade)
        
        # Envia uma confirmação.
        await interaction.followup.send(f'✅ **{len(deleted)}** mensagens apagadas por {interaction.user.mention}.', ephemeral=False)
        
    except discord.Forbidden:
        # O bot não tem as permissões necessárias (Gerenciar Mensagens)
        await interaction.followup.send("❌ Erro: O bot não tem permissão para apagar mensagens neste canal. Certifique-se de que ele tem a permissão 'Gerenciar Mensagens'.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Ocorreu um erro ao apagar mensagens: {e}", ephemeral=True)

# --- Comando de Apagar Canais (/apagar_canais) ---
@bot.tree.command(name='apagar_canais', description='APAGA TODOS OS CANAIS DO SERVIDOR. USE COM EXTREMA CAUTELA.')
@app_commands.checks.has_permissions(manage_channels=True)
async def apagar_canais_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    if interaction.guild is None:
        await interaction.followup.send("Este comando só pode ser usado em um servidor.", ephemeral=True)
        return

    channels_to_delete = interaction.guild.channels
    deleted_count = 0
    
    # Envia um aviso antes de começar
    await interaction.followup.send(f"⚠️ **ATENÇÃO:** Iniciando a exclusão de {len(channels_to_delete)} canais. Isso é irreversível.", ephemeral=True)

    for channel in channels_to_delete:
        try:
            await channel.delete()
            deleted_count += 1
        except discord.Forbidden:
            print(f"Não foi possível apagar o canal {channel.name} devido a permissões.")
        except Exception as e:
            print(f"Erro ao apagar o canal {channel.name}: {e}")

    await interaction.followup.send(f"✅ **{deleted_count}** canais foram apagados com sucesso.", ephemeral=False)

# --- Comando de Apagar Cargos (/apagar_cargos) ---
@bot.tree.command(name='apagar_cargos', description='APAGA TODOS OS CARGOS DO SERVIDOR (exceto @everyone e o do bot). USE COM EXTREMA CAUTELA.')
@app_commands.checks.has_permissions(manage_roles=True)
async def apagar_cargos_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    if interaction.guild is None:
        await interaction.followup.send("Este comando só pode ser usado em um servidor.", ephemeral=True)
        return

    # Filtra cargos: não apaga @everyone e só apaga cargos que estão abaixo do cargo mais alto do bot
    roles_to_delete = [role for role in interaction.guild.roles if role.name != '@everyone' and role < interaction.guild.me.top_role]
    deleted_count = 0
    
    # Envia um aviso antes de começar
    await interaction.followup.send(f"⚠️ **ATENÇÃO:** Iniciando a exclusão de {len(roles_to_delete)} cargos. Isso é irreversível.", ephemeral=True)

    for role in roles_to_delete:
        try:
            await role.delete()
            deleted_count += 1
        except discord.Forbidden:
            print(f"Não foi possível apagar o cargo {role.name} devido a permissões.")
        except Exception as e:
            print(f"Erro ao apagar o cargo {role.name}: {e}")

    await interaction.followup.send(f"✅ **{deleted_count}** cargos foram apagados com sucesso.", ephemeral=False)


# --- Execução do Bot ---
if TOKEN is None:
    print("ERRO: O token do bot não foi definido.")
else:
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("ERRO: O token do bot é inválido. Verifique se o token está correto.")
    except discord.PrivilegedIntentsRequired:
        print("ERRO: O 'Message Content Intent' e 'Member Intent' devem estar ativados no portal de desenvolvedores do Discord.")
