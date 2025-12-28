import discord
from discord.ext import commands, tasks
import requests
import json
from datetime import datetime
import os
from openai import OpenAI

# ============= CONFIGURATION =============
DISCORD_TOKEN = "MTQ0ODMyMDA5NDYxMzU0MTA2MA.GItAKx.YmFTyR9XFDblc3QmPB6iGFQTb56daQwux-Tq3A"
DEEPSEEK_API_KEY = "sk-4a0fcd9d8f524ac4b46f991ab326bd3a"
CHANNEL_ID = 1447684136788820008

# Configuration de recherche par défaut
CONFIG = {
    "search_text": "nike",
    "price_from": "20",
    "price_to": "60",
    "country": "fr",
    "check_interval": 5  # minutes
}

# ============= INITIALISATION =============
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

seen_items = set()
client_deepseek = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# ============= FONCTIONS =============

def fetch_vinted_items():
    """Récupère les annonces Vinted"""
    try:
        url = f"https://www.vinted.{CONFIG['country']}/api/v2/catalog/items"
        params = {
            "page": 1,
            "per_page": 20,
            "order": "newest_first"
        }
        
        if CONFIG.get("search_text"):
            params["search_text"] = CONFIG["search_text"]
        if CONFIG.get("price_from"):
            params["price_from"] = CONFIG["price_from"]
        if CONFIG.get("price_to"):
            params["price_to"] = CONFIG["price_to"]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": f"https://www.vinted.{CONFIG['country']}/"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.json().get("items", [])
        else:
            print(f"Erreur Vinted API: {response.status_code}")
            return []
    except Exception as e:
        print(f"Erreur: {e}")
        return []

def verify_with_ai(item):
    """Vérifie l'authenticité avec DeepSeek"""
    try:
        prompt = f"""Analyse cette annonce Vinted et réponds UNIQUEMENT en JSON strict :

Titre: {item.get('title', 'N/A')}
Marque: {item.get('brand_title', 'N/A')}
Prix: {item.get('price', 'N/A')}€
Description: {item.get('description', 'N/A')[:200]}
Taille: {item.get('size_title', 'N/A')}

Réponds au format JSON :
{{
  "authentique": true ou false,
  "confiance": 0-100,
  "raison": "explication courte",
  "prix_estime_min": nombre,
  "prix_estime_max": nombre
}}"""

        response = client_deepseek.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Tu es un expert en vérification d'articles de mode. Réponds UNIQUEMENT en JSON, sans texte avant ou après."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        
        return json.loads(content)
    except Exception as e:
        print(f"Erreur IA: {e}")
        return {
            "authentique": True,
            "confiance": 50,
            "raison": "Vérification impossible",
            "prix_estime_min": int(item.get('price', 0)),
            "prix_estime_max": int(item.get('price', 0)) + 20
        }

async def send_to_discord(item, ai_check):
    """Envoie l'annonce sur Discord"""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"Salon {CHANNEL_ID} introuvable")
            return
        
        color = 0x00ff00 if ai_check["authentique"] else 0xff0000
        
        embed = discord.Embed(
            title=item.get('title', 'Sans titre')[:256],
            url=f"https://www.vinted.{CONFIG['country']}/items/{item['id']}",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        if item.get('photo', {}).get('url'):
            embed.set_thumbnail(url=item['photo']['url'])
        
        embed.add_field(name="💰 Prix", value=f"{item.get('price', 'N/A')}€", inline=True)
        embed.add_field(name="🏷️ Marque", value=item.get('brand_title', 'Sans marque')[:1024], inline=True)
        embed.add_field(name="📏 Taille", value=item.get('size_title', 'N/A')[:1024], inline=True)
        embed.add_field(name="👤 Vendeur", value=item.get('user', {}).get('login', 'N/A')[:1024], inline=True)
        embed.add_field(name="📍 Lieu", value=item.get('user', {}).get('city', 'N/A')[:1024], inline=True)
        embed.add_field(name="👁️ Vues", value=str(item.get('view_count', 0)), inline=True)
        
        status = "✅ Semble authentique" if ai_check["authentique"] else "⚠️ Suspect"
        ai_text = f"{status}\nConfiance: {ai_check['confiance']}%\n{ai_check['raison'][:500]}"
        embed.add_field(name="🤖 Vérification IA", value=ai_text, inline=False)
        
        prix_marche = f"Entre {ai_check['prix_estime_min']}€ et {ai_check['prix_estime_max']}€"
        embed.add_field(name="💵 Prix du marché estimé", value=prix_marche, inline=False)
        
        embed.set_footer(text="Bot Vinted • Powered by DeepSeek AI")
        
        view = discord.ui.View()
        button = discord.ui.Button(
            label="🛒 Voir sur Vinted",
            style=discord.ButtonStyle.link,
            url=f"https://www.vinted.{CONFIG['country']}/items/{item['id']}"
        )
        view.add_item(button)
        
        await channel.send(embed=embed, view=view)
        print(f"✅ Annonce envoyée: {item.get('title')}")
        
    except Exception as e:
        print(f"Erreur Discord: {e}")

# ============= TÂCHE AUTOMATIQUE =============

@tasks.loop(minutes=CONFIG["check_interval"])
async def check_vinted():
    """Vérifie Vinted automatiquement"""
    print(f"🔍 Vérification Vinted... ({datetime.now().strftime('%H:%M:%S')})")
    
    items = fetch_vinted_items()
    new_count = 0
    
    for item in items:
        item_id = item.get("id")
        if item_id and item_id not in seen_items:
            ai_check = verify_with_ai(item)
            await send_to_discord(item, ai_check)
            seen_items.add(item_id)
            new_count += 1
    
    if new_count > 0:
        print(f"📦 {new_count} nouvelle(s) annonce(s) détectée(s)")
    else:
        print("⏳ Aucune nouvelle annonce")

# ============= COMMANDES DISCORD =============

@bot.command(name="filtrer")
async def filtrer(ctx, param: str, *values):
    """Change les filtres de recherche"""
    param = param.lower()
    
    if param in ["marque", "brand", "recherche", "search"]:
        CONFIG["search_text"] = " ".join(values)
        await ctx.send(f"✅ Recherche mise à jour : **{CONFIG['search_text']}**")
    
    elif param == "prix":
        if len(values) >= 2:
            CONFIG["price_from"] = values[0]
            CONFIG["price_to"] = values[1]
            await ctx.send(f"✅ Prix mis à jour : **{values[0]}€ - {values[1]}€**")
        else:
            await ctx.send("❌ Usage: `!filtrer prix MIN MAX`")
    
    elif param == "intervalle":
        try:
            minutes = int(values[0])
            if minutes >= 5:
                CONFIG["check_interval"] = minutes
                check_vinted.change_interval(minutes=minutes)
                await ctx.send(f"✅ Intervalle mis à jour : **{minutes} minutes**")
            else:
                await ctx.send("❌ L'intervalle doit être >= 5 minutes")
        except:
            await ctx.send("❌ Usage: `!filtrer intervalle MINUTES`")
    
    else:
        await ctx.send("❌ Paramètre invalide. Utilise: `marque`, `prix`, ou `intervalle`")

@bot.command(name="config")
async def config_cmd(ctx):
    """Affiche la configuration actuelle"""
    embed = discord.Embed(title="⚙️ Configuration actuelle", color=0x09B1BA)
    embed.add_field(name="🔍 Recherche", value=CONFIG.get("search_text", "Toutes"), inline=False)
    embed.add_field(name="💰 Prix", value=f"{CONFIG.get('price_from', '?')}€ - {CONFIG.get('price_to', '?')}€", inline=True)
    embed.add_field(name="⏰ Intervalle", value=f"{CONFIG['check_interval']} min", inline=True)
    embed.add_field(name="🌍 Pays", value=CONFIG["country"].upper(), inline=True)
    await ctx.send(embed=embed)

@bot.command(name="start")
async def start_cmd(ctx):
    """Démarre la surveillance"""
    if not check_vinted.is_running():
        check_vinted.start()
        await ctx.send("✅ Bot démarré ! Je surveille Vinted maintenant.")
    else:
        await ctx.send("⚠️ Le bot est déjà en cours d'exécution.")

@bot.command(name="stop")
async def stop_cmd(ctx):
    """Arrête la surveillance"""
    if check_vinted.is_running():
        check_vinted.cancel()
        await ctx.send("🛑 Bot arrêté.")
    else:
        await ctx.send("⚠️ Le bot n'est pas en cours d'exécution.")

@bot.command(name="aide")
async def aide(ctx):
    """Affiche l'aide"""
    embed = discord.Embed(title="📖 Commandes disponibles", color=0x09B1BA)
    embed.add_field(name="!filtrer marque [MARQUE]", value="Change la marque", inline=False)
    embed.add_field(name="!filtrer prix [MIN] [MAX]", value="Change la fourchette de prix", inline=False)
    embed.add_field(name="!filtrer intervalle [MINUTES]", value="Change la fréquence (min 5 min)", inline=False)
    embed.add_field(name="!config", value="Affiche la configuration", inline=False)
    embed.add_field(name="!start", value="Démarre la surveillance", inline=False)
    embed.add_field(name="!stop", value="Arrête la surveillance", inline=False)
    await ctx.send(embed=embed)

# ============= ÉVÉNEMENTS =============

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user}")
    print(f"🔍 Surveillance : {CONFIG['search_text']} ({CONFIG['price_from']}-{CONFIG['price_to']}€)")
    check_vinted.start()

# ============= LANCEMENT =============

if __name__ == "__main__":
    print("🚀 Démarrage du bot Vinted...")
    bot.run(DISCORD_TOKEN)
