import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import requests
from typing import Optional, Dict, Any, List

# Constantes da API do Discord
DISCORD_API_BASE = "https://discord.com/api/v10"

# --- Funções Auxiliares para API REST (User Token) ---

def api_request(method: str, endpoint: str, token: str, json_data: Optional[Dict[str, Any]] = None) -> requests.Response:
    """
    Faz uma requisição à API do Discord usando o User Token.
    """
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    url = f"{DISCORD_API_BASE}{endpoint}"
    
    if method == "GET":
        response = requests.get(url, headers=headers)
    elif method == "POST":
        response = requests.post(url, headers=headers, json=json_data)
    elif method == "PATCH":
        response = requests.patch(url, headers=headers, json=json_data)
    elif method == "PUT":
        response = requests.put(url, headers=headers, json=json_data)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers)
    else:
        raise ValueError(f"Método HTTP não suportado: {method}")
        
    return response

# --- Cog Principal ---

class ServerCloner(commands.Cog):
    """Comandos para clonar a estrutura de um servidor Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='clonar_servidor_user', description='Clona a estrutura de cargos e canais de um servidor usando um User Token.')
    @app_commands.describe(
        user_token='Seu User Token (Mantenha-o em segredo!)',
        origem_id='ID do servidor de origem (de onde copiar)',
        destino_id='ID do servidor de destino (para onde copiar)'
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def clone_server_user_slash(self, interaction: discord.Interaction, user_token: str, origem_id: str, destino_id: str):
        """
        Clona a estrutura de cargos e canais de um servidor para outro,
        usando um User Token para acessar o servidor de origem.
        """
        await interaction.response.defer(ephemeral=False)
        
        try:
            # 1. Obter o objeto Guild (Servidor) de destino (o bot precisa estar nele)
            guild_destino = self.bot.get_guild(int(destino_id))

            if not guild_destino:
                await interaction.followup.send(f"❌ Servidor de destino com ID `{destino_id}` não encontrado ou o bot não está nele.", ephemeral=False)
                return

            # 2. Verificar permissões do bot no servidor de destino
            if not guild_destino.me.guild_permissions.administrator:
                await interaction.followup.send("❌ O bot precisa da permissão **Administrador** no servidor de destino para realizar a clonagem.", ephemeral=False)
                return

            await interaction.followup.send(
                f"Iniciando clonagem do servidor de ID `{origem_id}` para **{guild_destino.name}**...",
                ephemeral=False
            )

            # --- Clonagem de Cargos ---
            role_mapping = await self.clone_roles_user(interaction, user_token, origem_id, guild_destino)

            # --- Clonagem de Canais e Categorias ---
            await self.clone_channels_user(interaction, user_token, origem_id, guild_destino, role_mapping)

            await interaction.followup.send(
                f"✅ **Clonagem Concluída!** A estrutura do servidor `{origem_id}` foi copiada para **{guild_destino.name}**.",
                ephemeral=False
            )

        except ValueError as ve:
            # Captura o erro de conversão de ID e tenta dar mais detalhes
            await interaction.followup.send(f"❌ Erro de ID inválido. Certifique-se de que todos os IDs fornecidos são números inteiros. Detalhe: `{ve}`", ephemeral=True)
        except Exception as e:
            print(f"Erro durante a clonagem: {e}")
            await interaction.followup.send(f"❌ Ocorreu um erro inesperado durante a clonagem: `{e}`", ephemeral=False)

    async def clone_roles_user(self, interaction: discord.Interaction, user_token: str, origem_id: str, guild_destino: discord.Guild) -> Dict[int, discord.Role]:
        """Copia os cargos do servidor de origem (via User Token) para o de destino (via Bot)."""
        
        # 1. Obter cargos do servidor de origem via API REST (User Token)
        response = await asyncio.to_thread(api_request, "GET", f"/guilds/{origem_id}/roles", user_token)
        
        if response.status_code != 200:
            await interaction.followup.send(f"❌ Falha ao obter cargos do servidor de origem. Código de status: {response.status_code}. Verifique o User Token e o ID do servidor de origem.", ephemeral=False)
            return {}
            
        roles_data: List[Dict[str, Any]] = response.json()
        
        # Filtra cargos @everyone e cargos gerenciados (bots, integrações)
        roles_to_copy = [
            role for role in roles_data 
            if not role.get('managed') and role.get('name') != '@everyone'
        ]
        
        # Ordena do mais baixo para o mais alto (pela posição, que é invertida na API)
        # A posição mais alta (maior número) é o cargo mais alto.
        roles_to_copy.sort(key=lambda r: r.get('position', 0))

        # Mapeamento de ID de cargo antigo (int) para objeto de cargo novo (discord.Role)
        role_mapping: Dict[int, discord.Role] = {}
        
        await interaction.followup.send(f"**Copiando {len(roles_to_copy)} cargos...**")

        for role in roles_to_copy:
            old_role_id = int(role['id'])
            
            # Prepara os dados para criação do cargo
            role_kwargs = {
                'name': role['name'],
                'permissions': discord.Permissions(int(role.get('permissions', 0))),
                'color': discord.Colour(role.get('color', 0)),
                'hoist': role.get('hoist', False),
                'mentionable': role.get('mentionable', False),
                'reason': f"Clonagem de servidor por {interaction.user.name}"
            }
            
            # Cria o novo cargo (via Bot)
            try:
                new_role = await guild_destino.create_role(**role_kwargs)
                role_mapping[old_role_id] = new_role
                await asyncio.sleep(1) # Pausa para evitar Rate Limit
            except discord.Forbidden:
                await interaction.followup.send(f"❌ Falha ao criar cargo `{role['name']}`: Permissões insuficientes do Bot no servidor de destino.", ephemeral=True)
                break
            except Exception as e:
                await interaction.followup.send(f"❌ Erro ao criar cargo `{role['name']}`: `{e}`", ephemeral=True)
                print(f"Erro ao criar cargo: {e}")
                
        await interaction.followup.send("✅ Cargos copiados. Ajustando hierarquia...")
        
        # A reordenação será feita implicitamente pela ordem de criação, mas para ser mais preciso,
        # seria necessário usar edit_role_positions, o que é complexo e propenso a erros de hierarquia.
        # Por enquanto, confiamos na ordem de criação.
        
        return role_mapping

    async def clone_channels_user(self, interaction: discord.Interaction, user_token: str, origem_id: str, guild_destino: discord.Guild, role_mapping: Dict[int, discord.Role]):
        """Copia categorias e canais do servidor de origem (via User Token) para o de destino (via Bot)."""
        
        # 1. Obter canais e categorias do servidor de origem via API REST (User Token)
        response = await asyncio.to_thread(api_request, "GET", f"/guilds/{origem_id}/channels", user_token)
        
        if response.status_code != 200:
            await interaction.followup.send(f"❌ Falha ao obter canais do servidor de origem. Código de status: {response.status_code}.", ephemeral=False)
            return
            
        channels_data: List[Dict[str, Any]] = response.json()
        
        # Ordena por posição para garantir a ordem correta de criação (categorias primeiro)
        channels_data.sort(key=lambda c: c.get('position', 0))

        # Mapeamento de ID de categoria antigo (int) para objeto de categoria novo (discord.CategoryChannel)
        category_mapping: Dict[int, discord.CategoryChannel] = {}
        
        await interaction.followup.send(f"**Copiando {len(channels_data)} canais e categorias...**")

        # Função auxiliar para mapear permissões de cargo
        def map_overwrites(overwrites: List[Dict[str, Any]]) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
            mapped = {}
            for overwrite in overwrites:
                # O tipo 0 é cargo, 1 é membro
                if overwrite['type'] == 0: 
                    # Garante que o ID é um número antes de converter
                    if not overwrite['id'].isdigit():
                        print(f"AVISO: ID de overwrite não numérico encontrado: {overwrite['id']}")
                        continue
                    old_role_id = int(overwrite['id'])
                    # Mapeia o ID do cargo antigo para o objeto do cargo novo
                    new_role = role_mapping.get(old_role_id)
                    
                    if new_role:
                        # O método from_pair aceita os valores inteiros (bitmasks) de allow e deny
                        allow_value = int(overwrite.get('allow', 0))
                        deny_value = int(overwrite.get('deny', 0))
                        
                        # Cria o PermissionOverwrite a partir dos valores inteiros
                        mapped[new_role] = discord.PermissionOverwrite.from_pair(
                            discord.Permissions(allow_value), 
                            discord.Permissions(deny_value)
                        )
                # Ignora overwrites de membros (type 1) pois não estamos clonando membros
            return mapped

        # 2. Criar Categorias
        for channel in channels_data:
            channel_type = channel.get('type')
            if channel_type == 4: # Category
                old_category_id = int(channel['id'])
                
                # Mapeia as permissões
                overwrites = map_overwrites(channel.get('permission_overwrites', []))
                
                try:
                    # Cria a nova categoria (via Bot)
                    new_category = await guild_destino.create_category(
                        name=channel['name'],
                        overwrites=overwrites,
                        reason=f"Clonagem de servidor por {interaction.user.name}"
                    )
                    category_mapping[old_category_id] = new_category
                    await asyncio.sleep(1) # Pausa para evitar Rate Limit
                except discord.Forbidden:
                    await interaction.followup.send(f"❌ Falha ao criar categoria `{channel['name']}`: Permissões insuficientes do Bot.", ephemeral=True)
                    break
                except Exception as e:
                    await interaction.followup.send(f"❌ Erro ao criar categoria `{channel['name']}`: `{e}`", ephemeral=True)
                    print(f"Erro ao criar categoria: {e}")

        # 3. Criar Canais (Texto, Voz, etc.)
        for channel in channels_data:
            channel_type = channel.get('type')
            if channel_type != 4: # Não é Categoria
                
                # Mapeia a categoria antiga para a nova
                new_category: Optional[discord.CategoryChannel] = None
                parent_id = channel.get('parent_id')
                if parent_id:
                    try:
                        parent_id_int = int(parent_id)
                        if parent_id_int in category_mapping:
                            new_category = category_mapping[parent_id_int]
                    except ValueError:
                        # Ignora se o parent_id não for um número (o que não deveria acontecer, mas previne o erro)
                        print(f"AVISO: parent_id inválido encontrado: {parent_id}")
                
                # Mapeia as permissões
                overwrites = map_overwrites(channel.get('permission_overwrites', []))
                
                # Parâmetros comuns
                channel_kwargs = {
                    'name': channel['name'],
                    'overwrites': overwrites,
                    'category': new_category,
                    'reason': f"Clonagem de servidor por {interaction.user.name}"
                }
                
                try:
                    if channel_type == 0: # Text Channel
                        await guild_destino.create_text_channel(
                            topic=channel.get('topic'),
                            slowmode_delay=channel.get('rate_limit_per_user'),
                            nsfw=channel.get('nsfw', False),
                            **channel_kwargs
                        )
                    elif channel_type == 2: # Voice Channel
                        await guild_destino.create_voice_channel(
                            user_limit=channel.get('user_limit'),
                            bitrate=channel.get('bitrate'),
                            **channel_kwargs
                        )
                    elif channel_type == 5: # Announcement Channel (News Channel)
                        # Discord.py não tem um create_announcement_channel direto, 
                        # mas podemos criar um Text Channel e depois convertê-lo via API,
                        # ou simplesmente criar como Text Channel. Vamos criar como Text Channel.
                        await guild_destino.create_text_channel(
                            topic=channel.get('topic'),
                            slowmode_delay=channel.get('rate_limit_per_user'),
                            nsfw=channel.get('nsfw', False),
                            **channel_kwargs
                        )
                    elif channel_type == 13: # Stage Channel
                        await guild_destino.create_stage_channel(
                            **channel_kwargs
                        )
                    # Ignoramos Forum (15) e outros tipos por simplicidade, mas a lógica é a mesma.
                        
                    await asyncio.sleep(1) # Pausa para evitar Rate Limit
                except discord.Forbidden:
                    await interaction.followup.send(f"❌ Falha ao criar canal `{channel['name']}`: Permissões insuficientes do Bot.", ephemeral=True)
                    break
                except Exception as e:
                    await interaction.followup.send(f"❌ Erro ao criar canal `{channel['name']}`: `{e}`", ephemeral=True)
                    print(f"Erro ao criar canal: {e}")
                    
        await interaction.followup.send("✅ Canais e categorias copiados.")

async def setup(bot: commands.Bot):
    """Função de setup para adicionar a cog ao bot."""
    # Remove o comando antigo (se existir) para evitar duplicidade
    try:
        bot.tree.remove_command('clonar_servidor')
    except:
        pass
        
    await bot.add_cog(ServerCloner(bot))
