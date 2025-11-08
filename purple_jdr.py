import os
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
import yt_dlp
import aiohttp
import concurrent.futures
import random
import re

# Chemin vers ffmpeg.exe
FFMPEG_PATH = r"C:\Users\fadeo\Downloads\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"

# === CONFIGURATION DE BASE ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# === DICTIONNAIRES JOUEURS ET SALONS ===
joueurs_dossier = {
    794941630695473172: "Purple_key",   # toi
    848606949565661197: "Marty",
    779378373792366592: "Antho",
    805587360552976404: "Ilan",
    887280670932606996: "Eden",
    836888012964364309: "Zoé",
    803621853176004618: "Maïa",
}

salons_status = {
    "Marty": "marty-individual",
    "Antho": "antho-individual",
    "Ilan": "ilan-individual",
    "Eden": "eden-individual",
    "Zoé": "zoe-individual",
    "Maïa": "nine-individual",
    "Purple_key": "purple_key-individual"
}

GITHUB_BASE = "https://raw.githubusercontent.com/Racekr/Purple_jdr/refs/heads/main/infos"
dernier_status = {}

# === MÉMOIRE POUR MUSIQUE ===
music_queues = {}  # guild.id -> [liste des URLs]
executor = concurrent.futures.ThreadPoolExecutor()

# ============================
# FONCTIONS ASYNC UTILES
# ============================
async def get_github_file(url):
    """Récupère un fichier GitHub de manière asynchrone"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text()
            return None

async def clear_messages(salon, limit=200):
    """Supprime les messages par batch pour éviter les rate limits"""
    total_deleted = 0
    while True:
        deleted = await salon.purge(limit=50)
        total_deleted += len(deleted)
        if len(deleted) < 50 or total_deleted >= limit:
            break
        await asyncio.sleep(0.5)
    return total_deleted

async def yt_info(query):
    """Extrait les infos de YouTube en thread pour ne pas bloquer"""
    loop = asyncio.get_running_loop()
    def run():
        ydl_opts = {"format": "bestaudio/best", "quiet": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)
    return await loop.run_in_executor(executor, run)

def get_queue(guild_id):
    return music_queues.setdefault(guild_id, [])

async def play_next(guild, voice_client):
    queue = get_queue(guild.id)
    if not queue:
        await voice_client.disconnect()
        return

    url = queue.pop(0)
    info = await yt_info(url)
    audio_url = info['url']
    titre = info.get('title', 'Titre inconnu')

    def after_play(error):
        fut = asyncio.run_coroutine_threadsafe(play_next(guild, voice_client), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"💥 Erreur after_play: {e}")

    voice_client.play(discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, options='-vn'), after=after_play)
    print(f"▶️ Lecture : {titre}")

# ============================
# BOUCLE STATUS
# ============================
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    global dernier_status
    for user_id, dossier in joueurs_dossier.items():
        url = f"{GITHUB_BASE}/{dossier}/status.txt"
        contenu = await get_github_file(url)
        if contenu:
            dernier_status[dossier] = contenu.strip()
            print(f"📥 Statut initial chargé pour {dossier}")
    verifier_status.start()

@tasks.loop(seconds=30)
async def verifier_status():
    for user_id, dossier in joueurs_dossier.items():
        if dossier == "Purple_key":
            continue
        url = f"{GITHUB_BASE}/{dossier}/status.txt"
        contenu = await get_github_file(url)
        if contenu and (dossier not in dernier_status or dernier_status[dossier] != contenu.strip()):
            dernier_status[dossier] = contenu.strip()
            salon_nom = salons_status.get(dossier)
            salon = discord.utils.get(bot.get_all_channels(), name=salon_nom)
            if salon:
                try:
                    await salon.send(f"**Mise à jour du `Status` de {dossier} :**\n```{contenu.strip()}```")
                    print(f"🔔 Nouveau status détecté pour {dossier}")
                except discord.HTTPException:
                    print(f"⚠️ Rate limit atteint pour {dossier}")

# ============================
# COMMANDE !i
# ============================
@bot.command()
async def i(ctx, nom_fichier: str = None):
    user_id = ctx.author.id

    # Si c'est toi et que tu es dans le salon perso de quelqu'un d'autre
    if user_id == 794941630695473172:
        salon_nom = ctx.channel.name
        dossier = None
        for d, s_nom in salons_status.items():
            if s_nom == salon_nom:
                dossier = d
                break
    else:
        # Pour les autres, on prend toujours leur propre dossier
        dossier = joueurs_dossier.get(user_id)

    if not dossier:
        await ctx.send("❌ Aucun dossier associé à ce salon ou à ton compte.")
        return

    if not nom_fichier:
        api_url = f"https://api.github.com/repos/Racekr/Purple_jdr/contents/infos/{dossier}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    fichiers = [item["name"] for item in await response.json() if item["name"].endswith(".txt")]
                    if fichiers:
                        liste = "\n".join(f"• `{f}`" for f in fichiers)
                        await ctx.send(f"📁 **Fichiers disponibles dans `{dossier}` :**\n{liste}")
                    else:
                        await ctx.send("📂 Aucun fichier trouvé dans ce dossier.")
                else:
                    await ctx.send("❌ Impossible d'accéder au dossier sur GitHub.")
        return

    raw_url = f"{GITHUB_BASE}/{dossier}/{nom_fichier}.txt"
    contenu = await get_github_file(raw_url)
    if contenu:
        if len(contenu) > 1900:
            await ctx.send("⚠️ Le fichier est trop long pour être affiché ici.")
        else:
            await ctx.send(f"📝 **Contenu de `{nom_fichier}.txt` :**\n```{contenu}```")
    else:
        await ctx.send("❌ Fichier introuvable sur GitHub.")

# ============================
# COMMANDES ADMIN
# ============================
@bot.group(name="a", invoke_without_command=True)
async def admin(ctx):
    if ctx.author.id != 794941630695473172:
        await ctx.send("⛔ Tu n’as pas la permission d’utiliser ces commandes.")
        return
    await ctx.send("🛠️ Commandes admin disponibles : `!a clear`, `!a status`")

@admin.command()
async def clear(ctx):
    if ctx.author.id != 794941630695473172:
        return
    total_deleted = 0
    for dossier, salon_nom in salons_status.items():
        if dossier == "Purple_key":
            continue
        salon = discord.utils.get(bot.get_all_channels(), name=salon_nom)
        if salon:
            deleted = await clear_messages(salon, limit=200)
            total_deleted += deleted
    await ctx.send(f"✅ Tous les salons individuels ont été nettoyés. ({total_deleted} messages supprimés)")

@admin.command()
async def status(ctx):
    if ctx.author.id != 794941630695473172:
        return
    for dossier, salon_nom in salons_status.items():
        if dossier == "Purple_key":
            continue
        url = f"{GITHUB_BASE}/{dossier}/status.txt"
        contenu = await get_github_file(url)
        if contenu:
            salon = discord.utils.get(bot.get_all_channels(), name=salon_nom)
            if salon:
                try:
                    await salon.send(f"📢 **Status actuel de {dossier} :**\n```{contenu.strip()}```")
                except discord.HTTPException:
                    print(f"⚠️ Rate limit atteint pour {dossier}")
    await ctx.send("✅ Statuts envoyés dans les salons correspondants.")

# ============================
# COMMANDES SALON PERSO
# ============================
@bot.group(name="p", invoke_without_command=True)
async def perso(ctx):
    await ctx.send("Commandes disponibles : `!p clear`")

@perso.command(name="clear")
async def clear_perso(ctx):
    salon_nom = salons_status.get(joueurs_dossier.get(ctx.author.id))
    if not salon_nom:
        await ctx.send("❌ Aucun salon individuel trouvé pour toi.")
        return

    salon = discord.utils.get(bot.get_all_channels(), name=salon_nom)
    if not salon:
        await ctx.send("❌ Salon introuvable.")
        return

    deleted = await clear_messages(salon, limit=200)
    await ctx.send(f"✅ {deleted} messages supprimés.", delete_after=5)

# ============================
# COMMANDES MUSIQUE OPTIMISÉES
# ============================
@bot.group(name="m", invoke_without_command=True)
async def m(ctx):
    await ctx.send("🎵 Commandes disponibles : `!m play <lien/recherche>`, `!m stop`, `!m skip`, `!m queue`")

def get_queue(guild_id):
    return music_queues.setdefault(guild_id, [])

async def yt_info(query):
    """Extrait les infos YouTube sans bloquer le bot"""
    loop = asyncio.get_running_loop()
    def run():
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'noplaylist': True,
            'default_search': 'ytsearch1',  # 1 résultat pour accélérer
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)
    return await loop.run_in_executor(None, run)

async def play_next(guild, voice_client):
    queue = get_queue(guild.id)
    if not queue:
        await voice_client.disconnect()
        return

    url = queue.pop(0)
    try:
        info = await yt_info(url)
        if 'entries' in info:
            info = info['entries'][0]
        audio_url = info['url']
        titre = info.get('title', 'Titre inconnu')
    except Exception as e:
        print(f"💥 Erreur lecture YouTube: {e}")
        await play_next(guild, voice_client)
        return

    def after_play(error):
        fut = asyncio.run_coroutine_threadsafe(play_next(guild, voice_client), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"💥 Erreur after_play: {e}")

    voice_client.play(discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, options='-vn'), after=after_play)
    print(f"▶️ Lecture : {titre}")

# ============================
# !m play
# ============================
@m.command()
async def play(ctx, *, query: str):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ Tu dois être dans un salon vocal pour jouer de la musique.")
        return

    async with ctx.typing():  # Indicateur de chargement
        channel = ctx.author.voice.channel
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if not voice_client:
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)

        try:
            info = await yt_info(query if query.startswith("http") else f"ytsearch:{query}")
            if 'entries' in info:
                info = info['entries'][0]
            url = info['webpage_url'] if 'webpage_url' in info else query
            titre = info.get("title", "Titre inconnu")
        except Exception as e:
            await ctx.send(f"❌ Impossible de récupérer la musique : {e}")
            return

        queue = get_queue(ctx.guild.id)
        queue.append(url)
        await ctx.send(f"✅ Ajouté à la queue : **{titre}**")

        if not voice_client.is_playing():
            await play_next(ctx.guild, voice_client)

# ============================
# !m stop
# ============================
@m.command()
async def stop(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client:
        get_queue(ctx.guild.id).clear()
        voice_client.stop()
        await voice_client.disconnect()
        await ctx.send("⏹️ Musique arrêtée et salon vocal quitté.")

# ============================
# !m skip
# ============================
@m.command()
async def skip(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("⏭️ Morceau suivant…")

# ============================
# !m queue
# ============================
@m.command()
async def queue(ctx):
    queue = get_queue(ctx.guild.id)
    if queue:
        # Affichage compact avec indices
        msg = "\n".join(f"{i+1}. {q}" for i, q in enumerate(queue))
        if len(msg) > 1900:  # Si trop long
            msg = msg[:1900] + "\n…et plus"
        await ctx.send("📄 Queue actuelle :\n" + msg)
    else:
        await ctx.send("📄 La queue est vide.")

# ============================
# COMMANDE !r LANCER DE DÉS
# ============================
@bot.command()
async def r(ctx, lancer: str):
    """
    Lance des dés. Format : NdX (ex: 1d6, 4d20)
    Types de dés autorisés : 4, 6, 8, 10, 12, 20, 100
    """
    match = re.fullmatch(r'(\d+)d(\d+)', lancer.lower())
    if not match:
        await ctx.send("❌ Format invalide. Utilise `NdX`, exemple : `4d6`")
        return

    nb_des, type_de = int(match.group(1)), int(match.group(2))

    # Limiter le type de dé aux autorisés
    if type_de not in [4, 6, 8, 10, 12, 20, 100]:
        await ctx.send("❌ Type de dé non autorisé. Choisis parmi 4, 6, 8, 10, 12, 20, 100.")
        return

    if nb_des < 1 or nb_des > 100:
        await ctx.send("❌ Nombre de dés invalide. Entre 1 et 100.")
        return

    # Lancer les dés
    resultats = [random.randint(1, type_de) for _ in range(nb_des)]
    total = sum(resultats)
    await ctx.send(f"🎲 Résultats du lancer {lancer} : {resultats} → **Total : {total}**")

# ============================
# COMMANDE !help
# ============================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="📝 Commandes du bot",
        color=discord.Color.blurple(),
        description="Voici la liste des commandes disponibles :"
    )

    # Commandes principales
    embed.add_field(
        name="Fichiers et statuts",
        value=(
            "`!i [nom_fichier]` : Affiche les fichiers de ton dossier (ou d'un autre si tu es Purple_key dans leur salon).\n"
            "`!p clear` : Nettoie ton salon individuel.\n"
            "`!a clear` : Nettoie tous les salons individuels (admin).\n"
            "`!a status` : Affiche les statuts de tous les joueurs (admin)."
        ),
        inline=False
    )

    # Musique
    embed.add_field(
        name="Musique",
        value=(
            "`!m play <lien/recherche>` : Joue un morceau ou l'ajoute à la queue.\n"
            "`!m stop` : Arrête la musique et quitte le salon vocal.\n"
            "`!m skip` : Passe au morceau suivant.\n"
            "`!m queue` : Affiche la queue actuelle."
        ),
        inline=False
    )

    # Dés
    embed.add_field(
        name="Lancer de dés",
        value=(
            "`!r NdX` : Lance N dés de type X.\n"
            "Exemples : `!r 1d6`, `!r 4d20`\n"
            "Types autorisés : 4, 6, 8, 10, 12, 20, 100."
        ),
        inline=False
    )

    await ctx.send(embed=embed)

# ============================
# LANCEMENT DU BOT
# ============================
bot.run(TOKEN)