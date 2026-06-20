import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import re
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_http():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run_http).start()

# ===== CONFIGURATION =====
import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
UNB_TOKEN = os.getenv("UNB_TOKEN")
GUILD_ID = 1516138323666669818

# Role IDs
ROLE_ID = 1517362960895311902  # Gamble God
GAMBLER_ROLE_ID = 1516138637409124363  # The Gambler
ECONOMY_MANAGER_ROLE_ID = 1517015911947702302  # Economy Manager

LOG_CHANNEL_NAME = "gamble-god-logs"
CASH_THRESHOLD = 10_000_000

CHECK_INTERVAL_MINUTES = 5
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def has_economy_manager():
    async def predicate(interaction: discord.Interaction):
        role = interaction.guild.get_role(ECONOMY_MANAGER_ROLE_ID)
        if role and role in interaction.user.roles:
            return True
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return False
    return app_commands.check(predicate)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRole):
        await ctx.send("❌ You don't have permission to use this command.")
        return
    raise error


async def send_log_embed(title: str, description: str, color: int):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if channel:
        embed = discord.Embed(title=title, description=description, color=color)
        await channel.send(embed=embed)


async def get_balance(session: aiohttp.ClientSession, user_id: int) -> int:
    url = f"https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/users/{user_id}"
    headers = {"Authorization": UNB_TOKEN, "Accept": "application/json"}
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("total", 0)
            elif response.status == 429:
                data = await response.json()
                wait = data.get("retry_after", 5)
                await asyncio.sleep(wait)
                return await get_balance(session, user_id)
            else:
                return 0
    except Exception:
        return 0


async def update_role(session: aiohttp.ClientSession, member: discord.Member):
    balance = await get_balance(session, member.id)
    role = member.guild.get_role(ROLE_ID)
    if not role:
        return
    has_role = role in member.roles
    if balance >= CASH_THRESHOLD and not has_role:
        await member.add_roles(role)
        await send_log_embed(title="🟢 Gamble God Assigned", description=f"**{member.name}** now has Gamble God!\nBalance: ${balance:,}", color=0x00ff00)
    elif balance < CASH_THRESHOLD and has_role:
        await member.remove_roles(role)
        await send_log_embed(title="🔴 Gamble God Removed", description=f"**{member.name}** lost Gamble God.\nBalance: ${balance:,}", color=0xff0000)
    return balance


@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def sync_gamblers():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    gambler_role = guild.get_role(GAMBLER_ROLE_ID)
    if not gambler_role:
        return
    gamblers = [m for m in guild.members if gambler_role in m.roles and not m.bot]
    await send_log_embed(title="🔄 Sync Started", description=f"Checking {len(gamblers)} gamblers...", color=0x3498db)
    async with aiohttp.ClientSession() as session:
        for i, member in enumerate(gamblers):
            try:
                await update_role(session, member)
                await asyncio.sleep(0.5)
                if (i + 1) % 50 == 0:
                    print(f"Synced {i+1}/{len(gamblers)}...")
            except Exception as e:
                print(f"Failed {member.name}: {e}")
    await send_log_embed(title="✅ Sync Complete", description=f"{len(gamblers)} gamblers checked.", color=0x00ff00)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print("Slash commands synced!")
    await send_log_embed(title="🚀 Bot Online", description="Bot is online and watching balances!", color=0x9b59b6)
    sync_gamblers.start()


# ===== PREFIX COMMANDS =====

@bot.command(name="check")
async def check_balance(ctx):
    async with aiohttp.ClientSession() as session:
        balance = await get_balance(session, ctx.author.id)
        await update_role(session, ctx.author)
    gambler_role = ctx.guild.get_role(GAMBLER_ROLE_ID)
    if gambler_role and gambler_role not in ctx.author.roles:
        await ctx.author.add_roles(gambler_role)
        await send_log_embed(title="🎰 Gambler Role Assigned", description=f"**{ctx.author.name}** got The Gambler role via `!check`", color=0xf1c40f)
    if balance >= CASH_THRESHOLD:
        await ctx.send(f"Your total balance is ${balance:,}. You are a Gamble God!")
    else:
        await ctx.send(f"Your total balance is ${balance:,}. You need ${CASH_THRESHOLD - balance:,} more for Gamble God.")


@bot.command(name="forcecheck")
@commands.has_role(ECONOMY_MANAGER_ROLE_ID)
async def force_check(ctx, member: discord.Member):
    async with aiohttp.ClientSession() as session:
        balance = await update_role(session, member)
    await ctx.send(f"**{member.name}** total balance: ${balance:,} — roles updated.")


@bot.command(name="purgegods")
@commands.has_role(ECONOMY_MANAGER_ROLE_ID)
async def purge_gods(ctx):
    guild = ctx.guild
    god_role = guild.get_role(ROLE_ID)
    if not god_role:
        await ctx.send("❌ Gamble God role not found.")
        return
    gods = [m for m in guild.members if god_role in m.roles and not m.bot]
    await ctx.send(f"🔍 Checking {len(gods)} Gamble Gods...")
    removed = 0
    async with aiohttp.ClientSession() as session:
        for member in gods:
            balance = await get_balance(session, member.id)
            if balance < CASH_THRESHOLD:
                await member.remove_roles(god_role)
                removed += 1
                await send_log_embed(title="🧹 Gamble God Purged", description=f"**{member.name}** lost Gamble God.\nBalance: ${balance:,}", color=0xff0000)
            await asyncio.sleep(0.5)
    await ctx.send(f"✅ Purge complete! Removed Gamble God from {removed} users.")


# ===== SLASH COMMANDS =====

@bot.tree.command(name="check", description="Check your balance and Gamble God status")
async def slash_check(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        balance = await get_balance(session, interaction.user.id)
        await update_role(session, interaction.user)
    gambler_role = interaction.guild.get_role(GAMBLER_ROLE_ID)
    if gambler_role and gambler_role not in interaction.user.roles:
        await interaction.user.add_roles(gambler_role)
        await send_log_embed(title="🎰 Gambler Role Assigned", description=f"**{interaction.user.name}** got The Gambler role via `/check`", color=0xf1c40f)
    if balance >= CASH_THRESHOLD:
        await interaction.response.send_message(f"Your total balance is ${balance:,}. You are a Gamble God!")
    else:
        await interaction.response.send_message(f"Your total balance is ${balance:,}. You need ${CASH_THRESHOLD - balance:,} more for Gamble God.")


@bot.tree.command(name="forcecheck", description="Check another user's balance (Economy Manager only)")
@app_commands.describe(member="The user to check")
@has_economy_manager()
async def slash_forcecheck(interaction: discord.Interaction, member: discord.Member):
    async with aiohttp.ClientSession() as session:
        balance = await update_role(session, member)
    await interaction.response.send_message(f"**{member.name}** total balance: ${balance:,} — roles updated.")


@bot.tree.command(name="purgegods", description="Remove Gamble God from everyone under threshold (Economy Manager only)")
@has_economy_manager()
async def slash_purgegods(interaction: discord.Interaction):
    guild = interaction.guild
    god_role = guild.get_role(ROLE_ID)
    if not god_role:
        await interaction.response.send_message("❌ Gamble God role not found.", ephemeral=True)
        return
    
    await interaction.response.send_message("🔍 Checking all Gamble Gods...")
    
    gods = [m for m in guild.members if god_role in m.roles and not m.bot]
    removed = 0
    async with aiohttp.ClientSession() as session:
        for member in gods:
            balance = await get_balance(session, member.id)
            if balance < CASH_THRESHOLD:
                await member.remove_roles(god_role)
                removed += 1
                await send_log_embed(title="🧹 Gamble God Purged", description=f"**{member.name}** lost Gamble God.\nBalance: ${balance:,}", color=0xff0000)
            await asyncio.sleep(0.5)
    
    await interaction.edit_original_response(content=f"✅ Purge complete! Removed Gamble God from {removed} users.")


bot.run(DISCORD_TOKEN)