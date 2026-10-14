import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import re
import json
import os
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
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
UNB_TOKEN = os.getenv("UNB_TOKEN")
GUILD_ID = 1516138323666669818

# Role IDs
ROLE_ID = 1517362960895311902  # Gamble God
GAMBLER_ROLE_ID = 1516138637409124363  # The Gambler
ECONOMY_MANAGER_ROLE_ID = 1527862603316068402  # Economy Manager
ECONOMY_ASSISTANT_ROLE_ID = 1559597519112118413  # Economy Assistant

LOG_CHANNEL_NAME = "gamble-god-logs"
ECONOMY_LOG_CHANNEL_NAME = "economy-logs"
TRANSACTION_LOG_CHANNEL = "transactions-logs"
CASH_THRESHOLD = 10_000_000
LARGE_AMOUNT_THRESHOLD = 50_000_000
OWNER_ID = 660361662565580840

CHECK_INTERVAL_MINUTES = 5

# Temp role system
TEMP_ACCESS_ROLE_ID = 1530185119699308746
TARGET_REWARD_ROLE_ID = 1516138694258720778

# Staff blacklist file
BLACKLIST_FILE = "staff_blacklist.json"
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ===== STAFF BLACKLIST FUNCTIONS =====

def load_blacklist():
    try:
        with open(BLACKLIST_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_blacklist(blacklist):
    with open(BLACKLIST_FILE, 'w') as f:
        json.dump(list(blacklist), f)

staff_blacklist = load_blacklist()


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


async def reverse_add_money(session: aiohttp.ClientSession, receiver_id: int, amount: int):
    """Reverse an add-money by subtracting the exact amount added."""
    url_get = f"https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/users/{receiver_id}"
    headers = {"Authorization": UNB_TOKEN, "Accept": "application/json", "Content-Type": "application/json"}
    
    try:
        async with session.get(url_get, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                cash = data.get("cash", 0)
                bank = data.get("bank", 0)
            else:
                return False
        
        remaining = amount
        if cash >= remaining:
            cash -= remaining
            remaining = 0
        else:
            remaining -= cash
            cash = 0
            if bank >= remaining:
                bank -= remaining
            else:
                bank = 0
        
        async with session.put(url_get, headers=headers, json={"cash": cash, "bank": bank}) as resp:
            return resp.status == 200
    except:
        return False


async def dm_owner(title: str, description: str, color: int):
    """Send a DM to the bot owner."""
    try:
        owner = bot.get_user(OWNER_ID)
        if owner:
            embed = discord.Embed(title=title, description=description, color=color)
            await owner.send(embed=embed)
    except:
        pass


@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def sync_gamblers():
    try:
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
                    await asyncio.sleep(5)
                    if (i + 1) % 10 == 0:
                        print(f"Synced {i+1}/{len(gamblers)}...")
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = e.response.headers.get('Retry-After', 5)
                        await send_log_message(f"⚠️ Discord rate limited. Waiting {retry_after}s...")
                        await asyncio.sleep(float(retry_after))
                    else:
                        print(f"Failed {member.name}: {e}")
                except Exception as e:
                    print(f"Failed {member.name}: {e}")
                    await asyncio.sleep(5)
        await send_log_embed(title="✅ Sync Complete", description=f"{len(gamblers)} gamblers checked.", color=0x00ff00)
    except Exception as e:
        await send_log_message(f"⚠️ Sync loop crashed: {e}. Restarting in 60s...")
        await asyncio.sleep(60)
        sync_gamblers.restart()


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
        
        lines = description.split('\n')
        
        user_line = [l for l in lines if "User:" in l][0] if any("User:" in l for l in lines) else ""
        staff_line = [l for l in lines if "Actioned by:" in l][0] if any("Actioned by:" in l for l in lines) else ""
        amount_line = [l for l in lines if "Amount:" in l][0] if any("Amount:" in l for l in lines) else ""
        
        receiver_id = None
        staff_id = None
        
        receiver_match = re.search(r'<@!?(\d+)>', user_line)
        staff_match = re.search(r'<@!?(\d+)>', staff_line)
        
        if receiver_match:
            receiver_id = int(receiver_match.group(1))
        if staff_match:
            staff_id = int(staff_match.group(1))
        
        nums = re.findall(r'[\d,]+', amount_line)
        
        amount = 0
        for n in nums:
            try:
                amount += int(n.replace(',', ''))
            except:
                pass
        
        if amount <= 0:
            await bot.process_commands(message)
            return
        
        receiver_display = f"<@{receiver_id}>" if receiver_id else "Unknown"
        staff_display = f"<@{staff_id}>" if staff_id else "Unknown"
        
        # Check if staff is blacklisted
        if staff_id and str(staff_id) in staff_blacklist:
            async with aiohttp.ClientSession() as session:
                reversed_success = await reverse_add_money(session, receiver_id, amount)
            
            status = "✅ Reversed!" if reversed_success else "❌ Reversal failed!"
            
            block_embed = discord.Embed(
                title="🚫 Add Money Blocked",
                description=f"**Staff:** {staff_display} (BLACKLISTED)\n**Receiver:** {receiver_display}\n**Amount:** ${amount:,}\n**Status:** {status}",
                color=0xff0000
            )
            await send_economy_log(embed=block_embed)
            await dm_owner(
                title="🚫 Add Money Blocked - Blacklisted Staff",
                description=f"**Staff:** {staff_display}\n**Receiver:** {receiver_display}\n**Amount:** ${amount:,}\n**Status:** {status}",
                color=0xff0000
            )
            return
        
        # Normal add-money logging
        log_embed = discord.Embed(
            title="💰 Add Money",
            description=f"**Staff:** {staff_display}\n**Receiver:** {receiver_display}\n**Amount:** ${amount:,}",
            color=0x00ff00
        )
        
        ping_content = None
        if amount >= LARGE_AMOUNT_THRESHOLD:
            ping_content = f"⚠️ <@{OWNER_ID}> Large add-money detected!"
        
        await send_economy_log(content=ping_content, embed=log_embed)
        await dm_owner(
            title="💰 Add Money Detected",
            description=f"**Staff:** {staff_display}\n**Receiver:** {receiver_display}\n**Amount:** ${amount:,}",
            color=0x00ff00
        )
        return

    await bot.process_commands(message)


# ===== TEMP ROLE SYSTEM =====

@bot.event
async def on_member_update(before, after):
    if TARGET_REWARD_ROLE_ID not in [r.id for r in before.roles] and TARGET_REWARD_ROLE_ID in [r.id for r in after.roles]:
        temp_role = after.guild.get_role(TEMP_ACCESS_ROLE_ID)
        if temp_role:
            try:
                await after.add_roles(temp_role, reason="Temporary access for 1M coin claim")
                print(f"✅ Added temp access role to {after.name}")
                await send_log_embed(
                    title="🎯 1M Coin Claim Access Granted",
                    description=f"**User:** {after.mention}\n**Expires:** In 60 seconds",
                    color=0x00ff00
                )
                await asyncio.sleep(60)
                if temp_role in after.roles:
                    await after.remove_roles(temp_role, reason="Temp access expired after 60s")
                    print(f"⏰ Removed temp access role from {after.name}")
                    await send_log_embed(
                        title="⏰ 1M Coin Claim Access Expired",
                        description=f"**User:** {after.mention}\n**Reason:** 60-second timer expired",
                        color=0xffa500
                    )
            except discord.HTTPException as e:
                print(f"❌ Failed to manage temp role for {after.name}: {e}")
            except Exception as e:
                print(f"❌ Unexpected error: {e}")


# ===== COMMANDS =====

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
@commands.has_any_role(ECONOMY_MANAGER_ROLE_ID, ECONOMY_ASSISTANT_ROLE_ID)
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
@commands.has_any_role(ECONOMY_MANAGER_ROLE_ID, ECONOMY_ASSISTANT_ROLE_ID)
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
            await asyncio.sleep(5)
    await ctx.send(f"✅ Purge complete! Removed Gamble God from {removed} users.")


@bot.command(name="staffblacklist")
@commands.has_role(ECONOMY_MANAGER_ROLE_ID)
async def staff_blacklist_cmd(ctx, member: discord.Member):
    staff_blacklist.add(str(member.id))
    save_blacklist(staff_blacklist)
    await ctx.send(f"🔒 **{member.name}** added to staff blacklist.")
    await send_log_message(f"🔒 **{ctx.author.name}** blacklisted staff **{member.name}**")


@bot.command(name="staffunblacklist")
@commands.has_role(ECONOMY_MANAGER_ROLE_ID)
async def staff_unblacklist_cmd(ctx, member: discord.Member):
    staff_blacklist.discard(str(member.id))
    save_blacklist(staff_blacklist)
    await ctx.send(f"🔓 **{member.name}** removed from staff blacklist.")
    await send_log_message(f"🔓 **{ctx.author.name}** unblacklisted staff **{member.name}**")


@bot.command(name="staffblacklisted")
@commands.has_role(ECONOMY_MANAGER_ROLE_ID)
async def staff_blacklisted_cmd(ctx):
    if not staff_blacklist:
        await ctx.send("No staff members are currently blacklisted.")
        return
    members = []
    for uid in staff_blacklist:
        member = ctx.guild.get_member(int(uid))
        if member:
            members.append(f"• {member.mention} ({member.name})")
        else:
            members.append(f"• Unknown ({uid})")
    embed = discord.Embed(title="🔒 Blacklisted Staff", description="\n".join(members), color=0xff0000)
    await ctx.send(embed=embed)


@bot.command(name="restock")
@commands.has_any_role(ECONOMY_MANAGER_ROLE_ID, ECONOMY_ASSISTANT_ROLE_ID)
async def restock_cmd(ctx, *, args: str = None):
    """Manually restock a store item. Usage: !restock <item name> <amount>"""
    
    if not args:
        await ctx.send("❌ Usage: `!restock <item name> <amount>`\nExample: `!restock Mystery Box 50`")
        return
    
    parts = args.rsplit(" ", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        await ctx.send("❌ Invalid format. Usage: `!restock <item name> <amount>`")
        return
    
    item_name = parts[0].strip()
    amount = int(parts[1])
    
    url = f"https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/items"
    headers = {"Authorization": UNB_TOKEN, "Accept": "application/json", "Content-Type": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await ctx.send(f"❌ Failed to fetch store items. Status: {resp.status}")
                return
            data = await resp.json()
            items = data.get("items", [])
        
        if not items:
            await ctx.send("❌ No items found in the store.")
            return
        
        matched = None
        for item in items:
            if item.get("name", "").lower() == item_name.lower():
                matched = item
                break
        
        if not matched:
            for item in items:
                if item_name.lower() in item.get("name", "").lower():
                    matched = item
                    break
        
        if not matched:
            await ctx.send(f"❌ No item found matching `{item_name}`.")
            return
        
        item_id = matched.get("id")
        await ctx.send(f"[DEBUG] Item: `{matched.get('name')}` | ID: `{item_id}` | Keys: `{list(matched.keys())}`")
        
        update_url = f"https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/items/{item_id}"
        
        async with session.put(update_url, headers=headers, json={"stock_remaining": amount}) as update_resp:
            if update_resp.status == 200:
                await ctx.send(f"✅ Restocked **{matched.get('name')}** to **{amount}**.")
                await send_economy_log(
                    embed=discord.Embed(
                        title="📦 Store Restocked",
                        description=f"**Staff:** {ctx.author.mention}\n**Item:** {matched.get('name')}\n**New Stock:** {amount}",
                        color=0x00ff00
                    )
                )
            else:
                error_text = await update_resp.text()
                await ctx.send(f"❌ Failed to restock. Status: {update_resp.status}\n`{error_text[:200]}`")


@bot.command(name="stock")
@commands.has_any_role(ECONOMY_MANAGER_ROLE_ID, ECONOMY_ASSISTANT_ROLE_ID)
async def stock_cmd(ctx):
    """View all store items and their current stock."""
    url = f"https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/items"
    headers = {"Authorization": UNB_TOKEN, "Accept": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await ctx.send("❌ Failed to fetch store items.")
                return
            data = await resp.json()
            items = data.get("items", [])
    
    if not items:
        await ctx.send("No items in the store.")
        return
    
    lines = []
    for item in items:
        if item.get("unlimited_stock"):
            stock_display = "∞"
        else:
            stock_display = str(item.get("stock_remaining", 0))
        lines.append(f"• **{item.get('name')}** — {stock_display}")
    
    embed = discord.Embed(
        title="📦 Store Stock",
        description="\n".join(lines),
        color=0x3498db
    )
    await ctx.send(embed=embed)


bot.run(DISCORD_TOKEN)