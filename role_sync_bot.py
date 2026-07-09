import discord
from discord.ext import commands, tasks
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
ECONOMY_LOG_CHANNEL_NAME = "economy-cmd-logs"
TRANSACTION_LOG_CHANNEL = "transactions-logs"
CASH_THRESHOLD = 10_000_000
LARGE_AMOUNT_THRESHOLD = 50_000_000
OWNER_ID = 660361662565580840

CHECK_INTERVAL_MINUTES = 5
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


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


async def send_log_message(content: str):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if channel:
        await channel.send(content)


async def send_economy_log(content: str = None, embed: discord.Embed = None):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    channel = discord.utils.get(guild.text_channels, name=ECONOMY_LOG_CHANNEL_NAME)
    if channel:
        await channel.send(content=content, embed=embed)


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
                await asyncio.sleep(2)
                if (i + 1) % 25 == 0:
                    print(f"Synced {i+1}/{len(gamblers)}...")
            except Exception as e:
                print(f"Failed {member.name}: {e}")
    await send_log_embed(title="✅ Sync Complete", description=f"{len(gamblers)} gamblers checked.", color=0x00ff00)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await asyncio.sleep(10)
    await send_log_embed(title="🚀 Bot Online", description="Bot is online and watching balances!", color=0x9b59b6)
    await asyncio.sleep(5)
    sync_gamblers.start()


@bot.event
async def on_message(message):
    if not message.guild or message.author == bot.user:
        return

    # Watch for UnbelievaBoat transactions in transactions-logs
    if message.channel.name == TRANSACTION_LOG_CHANNEL and message.embeds:
        embed = message.embeds[0]
        
        if not embed.author or "Balance updated" not in str(embed.author.name):
            await bot.process_commands(message)
            return
        
        if not embed.description:
            await bot.process_commands(message)
            return
        
        description = embed.description
        
        if "add-money" not in description.lower():
            await bot.process_commands(message)
            return
        
        # Parse line by line - grab everything after the colon
        lines = description.split('\n')
        receiver_name = None
        staff_name = None
        
        for line in lines:
            line = line.strip()
            if "User:" in line:
                receiver_name = line.split(":", 1)[1].strip().lstrip("@").strip()
            elif "Actioned by:" in line:
                staff_name = line.split(":", 1)[1].strip().lstrip("@").strip()
        
        if not receiver_name or not staff_name:
            await send_log_message(f"[DEBUG] Parse failed. Receiver: {receiver_name}, Staff: {staff_name}")
            await bot.process_commands(message)
            return
        
        # Look up members by name
        receiver = discord.utils.get(message.guild.members, name=receiver_name)
        staff = discord.utils.get(message.guild.members, name=staff_name)
        
        if not receiver:
            receiver = discord.utils.get(message.guild.members, display_name=receiver_name)
        if not staff:
            staff = discord.utils.get(message.guild.members, display_name=staff_name)
        
        receiver_display = receiver.name if receiver else receiver_name
        staff_display = staff.name if staff else staff_name
        receiver_id = receiver.id if receiver else 0
        staff_id = staff.id if staff else 0
        
        # Calculate total amount
        amount = 0
        cash_match = re.search(r'Cash:\s*\+?([\d,]+)', description)
        bank_match = re.search(r'Bank:\s*\+?([\d,]+)', description)
        
        if cash_match:
            cash_val = int(cash_match.group(1).replace(',', ''))
            amount += cash_val
        if bank_match:
            bank_val = int(bank_match.group(1).replace(',', ''))
            amount += bank_val
        
        if amount <= 0:
            await bot.process_commands(message)
            return
        
        # Create embed for economy-cmd-logs
        log_embed = discord.Embed(
            title="💰 Add Money",
            description=f"**Staff:** {staff_display}\n**Receiver:** {receiver_display}\n**Amount:** ${amount:,}",
            color=0x00ff00
        )
        log_embed.set_footer(text=f"Receiver ID: {receiver_id} | Staff ID: {staff_id}")
        
        ping_content = None
        if amount >= LARGE_AMOUNT_THRESHOLD:
            ping_content = f"⚠️ <@{OWNER_ID}> Large add-money detected!"
        
        await send_economy_log(content=ping_content, embed=log_embed)
        return

    await bot.process_commands(message)


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


@bot.command(name="syncall")
@commands.has_role(ECONOMY_MANAGER_ROLE_ID)
async def sync_all(ctx):
    await ctx.send("⚡ Restarting sync cycle...")
    sync_gamblers.restart()
    await ctx.send("✅ Sync cycle restarted! Running full sync now...")


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
            await asyncio.sleep(2)
    await ctx.send(f"✅ Purge complete! Removed Gamble God from {removed} users.")


bot.run(DISCORD_TOKEN)