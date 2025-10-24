# Format Python code here
import asyncio
import io
import json
import os
import platform
import random
import re
import time
import traceback
from datetime import UTC, datetime, timedelta, timezone
from difflib import get_close_matches

import aiohttp
import discord
import psutil
import requests
from discord.ext import commands, tasks
from discord.ui import Button, Select, View
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

WARN_FILE = "warns.json"
RR_FILE = "reaction_roles.json"
# ------------------ Load Token ------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ------------------ Bot Config ------------------

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")  # Optional if you have a custom help command


BOT_NAME = "SX2 Enforcer"

# ------------------ Events ------------------
@bot.event
async def on_ready():
    print(f"✅ {BOT_NAME} is online as {bot.user}!")
    await bot.change_presence(activity=discord.Game(name="!help for commands"))


# Welcome new members
@bot.event
async def on_member_join(member):
    # Find the welcome channel
    channel = discord.utils.get(member.guild.text_channels, name="👋⤬welcome")
    if not channel:
        return

    # Option 1: Static GIF or PNG URL (replace with your preferred GIF)
    gif_url = "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"

    # Option 2 (optional): fetch a random "welcome" GIF from Giphy API
    # You need a Giphy API key for this
    """
    api_key = "Z5KFtufwUijOIDVHkXkEzmMnCpzH1nDa"
    search = requests.get(f"https://api.giphy.com/v1/gifs/search?api_key={api_key}&q=welcome&limit=1")
    data = search.json()
    if data['data']:
        gif_url = data['data'][0]['images']['downsized_large']['url']
    else:
        gif_url = "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
    """

    # Create an embed
    embed = discord.Embed(
        title=f"🎉 Welcome to {member.guild.name}!",
        description=f"Hey {member.mention}, we're thrilled to have you here! 🎈",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="👤 Member Name", value=str(member), inline=True)
    embed.add_field(name="🆔 Member ID", value=str(member.id), inline=True)
    embed.add_field(
        name="📅 Account Created",
        value=member.created_at.strftime("%b %d, %Y"),
        inline=False,
    )
    embed.set_footer(text=f"Member #{member.guild.member_count}")

    # Set the GIF/PNG as the embed image
    embed.set_image(url=gif_url)

    # Send the embed
    await channel.send(embed=embed)


# ------------------ Data Persistence ------------------
# load warns
try:
    if os.path.exists(WARN_FILE):
        with open(WARN_FILE, "r") as f:
            warns = json.load(f)
            # if keys are strings, convert to int keys for convenience (optional)
            warns = {int(k): int(v) for k, v in warns.items()}
    else:
        warns = {}
except Exception:
    warns = {}

# load reaction_roles (message_id -> {emoji: role_id})
try:
    if os.path.exists(RR_FILE):
        with open(RR_FILE, "r") as f:
            reaction_roles = json.load(f)
            # convert keys to ints where appropriate
            reaction_roles = {
                int(k): {ek: int(ev) for ek, ev in v.items()}
                for k, v in reaction_roles.items()
            }
    else:
        reaction_roles = {}
except Exception:
    reaction_roles = {}

# autosave task
@tasks.loop(seconds=60.0)
async def autosave_data():
    try:
        with open(WARN_FILE, "w") as f:
            json.dump({str(k): v for k, v in warns.items()}, f, indent=2)
        with open(RR_FILE, "w") as f:
            json.dump(
                {
                    str(k): {ek: ev for ek, ev in v.items()}
                    for k, v in reaction_roles.items()
                },
                f,
                indent=2,
            )
    except Exception as e:
        print("Autosave error:", e)


@bot.event
async def on_ready():
    # start autosave if not running
    if not autosave_data.is_running():
        autosave_data.start()
    # existing on_ready actions follow...
    print(f"✅ {BOT_NAME} is online as {bot.user}!")
    await bot.change_presence(activity=discord.Game(name="Enforcing the Server"))


# ---------------- Role Removal Detection ----------------
@bot.event
async def on_member_update(before, after):
    """Detect role removals and log + DM the user."""
    try:
        # Detect removed roles (roles that existed before but not after)
        removed_roles = [role for role in before.roles if role not in after.roles]
        if not removed_roles:
            return  # No roles removed, ignore

        # Get log channel (replace with your actual log channel ID)
        log_channel_id = 1422329487227355366  # 🔧 CHANGE THIS
        log_channel = bot.get_channel(log_channel_id)

        # Build message
        removed_names = ", ".join([role.name for role in removed_roles])

        # 📨 Send DM to the user
        try:
            await after.send(
                f"⚠️ One or more roles were removed from your account in **{after.guild.name}**:\n"
                f"❌ **Removed:** {removed_names}\n\n"
                "If you believe this was a mistake, please contact a server moderator."
            )
        except discord.Forbidden:
            # User's DMs are closed
            if log_channel:
                await log_channel.send(
                    f"📪 Could not DM **{after}** about role removal: DMs closed."
                )

        # 🧾 Log in the moderation log channel
        if log_channel:
            embed = discord.Embed(
                title="🚨 Role Removal Logged",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="👤 Member", value=f"{after.mention} ({after.id})", inline=False
            )
            embed.add_field(name="🧾 Roles Removed", value=removed_names, inline=False)
            embed.set_footer(text=f"Guild: {after.guild.name}")
            await log_channel.send(embed=embed)

    except Exception as e:
        print(f"⚠️ Error in on_member_update: {e}")


# ---------------- Help System ----------------
# Data structure: category -> list of (command, description, usage)
HELP_CATEGORIES = {
    "General": [
        ("invite", "Get the bot invite link.", "!invite"),
        ("help", "Show this help message.", "!help"),
        ("ping", "Check bot latency.", "!ping"),
        ("bot_info", "Get bot info.", "!bot_info"),
        (
            "clear",
            "Delete last N messages. Requires manage messages permission.",
            "!clear <amount>",
        ),
        (
            "say",
            "Make the bot say something. Requires manage messages permission.",
            "!say <message>",
        ),
        ("serverinfo", "Get server information.", "!serverinfo"),
        ("userinfo", "Get user information.", "!userinfo [@user]"),
    ],
    "Moderation": [
        ("kick", "Kick a member. Requires kick permissions.", "!kick @user <reason>"),
        ("ban", "Ban a member. Requires ban permissions.", "!ban @user <reason>"),
        (
            "unban",
            "Unban a member by ID. Requires ban permissions.",
            "!unban <user_id> <reason>",
        ),
        (
            "warn",
            "Warn a member. Kicks after 3 warnings. Requires kick permissions.",
            "!warn @user <reason>",
        ),
        (
            "checkwarnings",
            "Check how many warnings a member has.",
            "!checkwarnings @user",
        ),
        (
            "clearwarn",
            "Clear warnings for a member. Requires kick permissions.",
            "!clearwarn @user",
        ),
        (
            "mute",
            "Mute a member. Requires manage roles permission.",
            "!mute @user <reason>",
        ),
        (
            "mutetime",
            "Check remaining mute time. Requires manage roles permission.",
            "!mutetime",
        ),
        (
            "tempmute",
            "Temporarily mute a member. Requires manage roles permission.",
            "!tempmute @user <time> [m/h/d]",
        ),
        (
            "unmute",
            "Unmute a member. Requires manage roles permission.",
            "!unmute @user",
        ),
        (
            "softban",
            "Softban a member (ban and unban). Requires ban permissions.",
            "!softban @user <reason>",
        ),
        (
            "lockdown",
            "Lock a channel. Requires manage channels permission.",
            "!lockdown [#channel]",
        ),
        (
            "unlock",
            "Unlock a channel. Requires manage channels permission.",
            "!unlock [#channel]",
        ),
        (
            "nick",
            "Change a member's nickname. Requires manage nicknames permission.",
            "!nick @user <new_nickname>",
        ),
        (
            "announce",
            "Make an announcement in the current channel. Requires administrator permission.",
            "!announce <message>",
        ),
        (
            "purgebot",
            "Delete bot messages only. Requires manage messages permission.",
            "!purgebot <amount>",
        ),
        (
            "warnings",
            "View warnings for a member. Requires kick permissions.",
            "!warnings @user",
        ),
        (
            "slowmode",
            "Set slowmode for a channel. Requires manage channels permission.",
            "!slowmode #channel <seconds>",
        ),
    ],
    "Server Setup / Utilities": [
        (
            "setupserver",
            "Interactive server setup wizard. Requires administrator permission.",
            "!setupserver",
        ),
        (
            "deleterole",
            "Delete a role by name. Requires manage roles permission.",
            "!deleterole <role_name>",
        ),
        (
            "deletechannel",
            "Delete a channel by name. Requires manage channels permission.",
            "!deletechannel <channel_name>",
        ),
        (
            "renamechannel",
            "Rename a channel. Requires manage channels permission.",
            "!renamechannel <old_name> <new_name>",
        ),
        (
            "renamerole",
            "Rename a role. Requires manage roles permission.",
            "!renamerole <old_name> <new_name>",
        ),
        (
            "add_role",
            "Create a role with a custom name. Requires administrator permission.",
            "!add_role <role_name>",
        ),
        (
            "addtext",
            "Create a text channel with a custom name. Requires administrator permission.",
            "!addtext <channel_name>",
        ),
        (
            "addvoice",
            "Create a voice channel with a custom name. Requires administrator permission.",
            "!addvoice <channel_name>",
        ),
        (
            "addrole",
            "Add a role to a member. Requires manage roles permission.",
            "!addrole @user @role",
        ),
        (
            "removerole",
            "Remove a role from a member. Requires manage roles permission.",
            "!removerole @user @role",
        ),
        (
            "temprole",
            "Temporarily assign a role to a member. Requires manage roles permission.",
            "!temprole @user @role <time_in_seconds>",
        ),
        (
            "massrole",
            "Assign a role to all members. Requires administrator permission.",
            "!massrole @role",
        ),
        ("roleinfo", "Get information about a role.", "!roleinfo @role"),
        (
            "reactionrole",
            "Set up a reaction role message. Requires manage messages permission.",
            "!reactionrole #channel <message_id> <emoji> @role",
        ),
    ],
}

# Configuration
ITEMS_PER_PAGE = 4


def make_help_embed(category: str, page: int = 0):
    """Return a discord.Embed for the given category and page."""
    commands_list = HELP_CATEGORIES.get(category, [])
    total_items = len(commands_list)
    pages = max(1, (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, pages - 1))

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    chunk = commands_list[start:end]

    embed = discord.Embed(
        title=f"**{category} Commands**",
        description=f"Page **{page+1}/{pages}** — Use the buttons or select menu to navigate categories.",
        color=discord.Color.gold(),
    )

    for cmd, desc, usage in chunk:
        embed.add_field(
            name=f"**{cmd}**", value=f"{desc}\nUsage: `{usage}`", inline=False
        )

    embed.set_footer(text="Tip: Use ! before commands. Slash commands coming soon!")
    return embed, pages


# ---------------- Help View ----------------
class HelpView(View):
    def __init__(self, author_id: int, initial_category: str = "General"):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.category = initial_category
        self.page = 0
        self.max_pages = 1

        # Select menu for categories
        options = [
            discord.SelectOption(
                label=cat, description=f"{len(HELP_CATEGORIES[cat])} commands"
            )
            for cat in HELP_CATEGORIES
        ]
        self.add_item(
            Select(
                placeholder="Choose category...",
                options=options,
                custom_id="help_select",
            )
        )

        # Navigation buttons
        self.prev_button = Button(label="⬅ Prev", style=discord.ButtonStyle.secondary)
        self.next_button = Button(label="Next ➡", style=discord.ButtonStyle.secondary)
        self.close_button = Button(label="Close ❌", style=discord.ButtonStyle.danger)

        self.prev_button.callback = self.on_prev
        self.next_button.callback = self.on_next
        self.close_button.callback = self.on_close

        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.close_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help panel isn't for you.", ephemeral=True
            )
            return False
        return True

    async def on_prev(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.page = max(0, self.page - 1)
        embed, pages = make_help_embed(self.category, self.page)
        self.max_pages = pages
        await interaction.followup.edit_message(
            interaction.message.id, embed=embed, view=self
        )

    async def on_next(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        _, pages = make_help_embed(self.category, self.page)
        self.max_pages = pages
        self.page = min(self.max_pages - 1, self.page + 1)
        embed, _ = make_help_embed(self.category, self.page)
        await interaction.followup.edit_message(
            interaction.message.id, embed=embed, view=self
        )

    async def on_close(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.followup.edit_message(
                interaction.message.id,
                content="Help panel closed.",
                embed=None,
                view=None,
            )
        except Exception:
            pass
        self.stop()


# ---------------- Select Callback ----------------
@discord.ui.select(custom_id="help_select")
async def help_select_callback(
    select: discord.ui.Select, interaction: discord.Interaction
):
    view: HelpView = select.view
    if not view:
        await interaction.response.send_message(
            "This help panel has expired.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    view.category = select.values[0]
    view.page = 0
    embed, pages = make_help_embed(view.category, view.page)
    view.max_pages = pages
    await interaction.followup.edit_message(
        interaction.message.id, embed=embed, view=view
    )


Select.callback = help_select_callback

# ---------------- General Commands ----------------

# ----- Invite Command -----
import datetime

now = datetime.datetime.now()
# Global stats (updated in background)
bot_stats = {"guilds": 0, "users": 0}

# Background task to keep stats live
@tasks.loop(minutes=5)
async def update_bot_stats():
    bot_stats["guilds"] = len(bot.guilds)
    bot_stats["users"] = sum(g.member_count for g in bot.guilds)


@update_bot_stats.before_loop
async def before_update_bot_stats():
    await bot.wait_until_ready()
    bot_stats["guilds"] = len(bot.guilds)
    bot_stats["users"] = sum(g.member_count for g in bot.guilds)


@bot.command(name="invite", aliases=["botinfo", "sx2"])
async def invite(ctx):
    """Shows SX2 bot info, features, and invite links."""

    # Ensure stats are ready
    if not update_bot_stats.is_running():
        update_bot_stats.start()

    guild_count = bot_stats["guilds"]
    user_count = bot_stats["users"]

    # Generate bot invite link
    permissions = discord.Permissions(
        manage_roles=True,
        manage_channels=True,
        kick_members=True,
        ban_members=True,
        manage_messages=True,
        read_messages=True,
        send_messages=True,
        embed_links=True,
        attach_files=True,
        read_message_history=True,
        use_external_emojis=True,
        connect=True,
        speak=True,
        moderate_members=True,
    )

    invite_url = discord.utils.oauth_url(
        bot.user.id, permissions=permissions, scopes=("bot", "applications.commands")
    )

    # Optional links
    support_server = "https://discord.gg/K7mVVP4YPB"
    website = "https://sx2bot.com"  # (if you create one later)
    vote_url = "https://top.gg/bot/YOUR_BOT_ID"  # Optional voting page

    # 🧩 Core features of SX2
    feature_list = [
        "🧱 **Server Setup Wizard** — Build complete servers with roles, channels & permissions.",
        "🎭 **Reaction Roles** — Let users self-assign roles using emoji reactions.",
        "🛡️ **Smart Moderation** — Kick, ban, warn, mute & log everything automatically.",
        "📋 **Logging System** — Track role changes, joins, leaves, bans, and edits.",
        "🎉 **Welcome & Leave System** — Greet members with custom messages & images.",
        "⚙️ **Customizable Prefix** — Change commands to match your server style.",
        "🔧 **Utility Tools** — Purge messages, get user info, check latency, and more.",
    ]

    embed = discord.Embed(
        title=f"🤖 Meet {bot.user.name}!",
        description=(
            f"Hey **{ctx.author.name}**, I'm **{bot.user.name}** — your smart Discord management assistant.\n\n"
            f"I'm currently active in **{guild_count:,} servers** and managing **{user_count:,} members**!\n\n"
            f"**Here’s what I can do for your server:**\n"
            f"{chr(10).join(feature_list)}\n\n"
            f"🌐 Click the buttons below to invite or explore more!\n\n"
            f"**:question: !help to see all my commands**."
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(
        text="SX2 • Smart, Fast & Reliable", icon_url=bot.user.display_avatar.url
    )

    # 🧭 Buttons for quick actions
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="➕ Invite Me", url=invite_url, style=discord.ButtonStyle.link
        )
    )
    view.add_item(
        discord.ui.Button(
            label="💬 Support Server", url=support_server, style=discord.ButtonStyle.link
        )
    )
    view.add_item(
        discord.ui.Button(
            label="🌍 Website", url=website, style=discord.ButtonStyle.link
        )
    )
    view.add_item(
        discord.ui.Button(
            label="⭐ Vote for SX2", url=vote_url, style=discord.ButtonStyle.link
        )
    )

    await ctx.send(embed=embed, view=view)


# ----invite command end----


# ---------------- General Commands ----------------


import discord
from discord.ext import commands


@commands.has_permissions(administrator=True)
@bot.command(name="setup_support")
async def setup_support(ctx):
    """Sets up the official SX2 Enforcer Support Server structure"""
    guild = ctx.guild
    await ctx.send(
        "⚙️ Setting up your **SX2 Enforcer Support Server**... Please wait a moment!"
    )

    # --- Create Roles ---
    roles_to_create = [
        ("👑 Owner", discord.Colour.red()),
        ("🛡 Admin", discord.Colour.purple()),
        ("🔧 Support", discord.Colour.blue()),
        ("🤖 Bot", discord.Colour.green()),
        ("💬 Member", discord.Colour.light_grey()),
    ]

    for role_name, color in roles_to_create:
        existing = discord.utils.get(guild.roles, name=role_name)
        if not existing:
            await guild.create_role(name=role_name, colour=color)
            await ctx.send(f"✅ Created role: {role_name}")
        else:
            await ctx.send(f"ℹ️ Role `{role_name}` already exists.")

    # --- Create Categories and Channels ---
    structure = {
        "🟢 INFORMATION": [
            "📢・announcements",
            "📚・how-to-use",
            "📎・invite-links",
            "🪪・rules",
        ],
        "🔧 SUPPORT": [
            "💬・help-desk",
            "🧾・bug-reports",
            "💡・suggestions",
        ],
        "👥 COMMUNITY": [
            "💭・general-chat",
            "🤝・showcase",
        ],
        "🚨 STAFF ZONE": [
            "🧰・staff-chat",
            "📋・log-channel",
        ],
    }

    for category_name, channels in structure.items():
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)
            await ctx.send(f"📁 Created category: {category_name}")

        for channel_name in channels:
            existing_channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not existing_channel:
                await guild.create_text_channel(channel_name, category=category)
                await ctx.send(f"📝 Created channel: {channel_name}")

    await ctx.send("🎉 Setup complete! Your **SX2 Enforcer Support Server** is ready!")


# ---------------- General Commands ----------------
# ---------------- General Commands ----------------


@bot.command(name="help")
async def prefix_help(ctx):
    embed, pages = make_help_embed("General", 0)
    view = HelpView(author_id=ctx.author.id, initial_category="General")
    view.max_pages = pages
    await ctx.send(embed=embed, view=view)


# ---------------- INFO COMMANDS ----------------
@bot.command(name="ping")
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")


# bot info command
# Record bot start time when it launches
bot.launch_time = time.time()


@bot.command(name="bot_info")
async def botinfo(ctx):
    """Displays information about the bot."""
    current_time = time.time()
    uptime_seconds = int(current_time - bot.launch_time)
    uptime_str = datetime.fromtimestamp(uptime_seconds, tz=UTC).strftime("%Hh %Mm %Ss")

    # Basic info
    bot_user = bot.user
    latency = round(bot.latency * 1000)
    servers = len(bot.guilds)
    total_users = sum(g.member_count for g in bot.guilds)
    python_version = platform.python_version()
    discord_version = discord.__version__
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent

    embed = discord.Embed(
        title=f"🤖 Bot Information — {bot_user.name}",
        color=discord.Color.green(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=bot_user.display_avatar.url)

    # ─── GENERAL INFO ───────────────────────────────
    general = (
        f"**• Bot Name:** {bot_user.name}\n"
        f"**• Identifier:** `{bot_user.id}`\n"
        f"**• Uptime:** {uptime_str}\n"
        f"**• Latency:** {latency} ms"
    )
    embed.add_field(name="🧾 GENERAL INFO", value=general, inline=False)

    # Space / Separator
    embed.add_field(name="\u200b", value="──────────────────────────────", inline=False)

    # ─── PERFORMANCE ───────────────────────────────
    performance = (
        f"**• CPU Usage:** {cpu_usage}%\n"
        f"**• RAM Usage:** {ram_usage}%\n"
        f"**• Python Version:** {python_version}\n"
        f"**• Discord.py Version:** {discord_version}"
    )
    embed.add_field(name="⚙️ PERFORMANCE", value=performance, inline=False)

    # Space / Separator
    embed.add_field(name="\u200b", value="──────────────────────────────", inline=False)

    # ─── ACTIVITY / STATS ───────────────────────────
    stats = (
        f"**• Connected Servers:** {servers}\n"
        f"**• Total Users (Approx):** {total_users:,}\n"
        f"**• Command Prefix:** `{bot.command_prefix}`"
    )
    embed.add_field(name="📊 ACTIVITY / STATS", value=stats, inline=False)

    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )
    await ctx.send(embed=embed)


# ---------------- SERVER & USER INFO COMMANDS ----------------
@bot.command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild

    # Find the most active text channel (by message count if cached, fallback to highest position)
    text_channels = [
        ch for ch in guild.text_channels if ch.permissions_for(guild.me).read_messages
    ]
    active_channel = (
        max(text_channels, key=lambda c: c.position) if text_channels else None
    )

    # Basic data
    owner = guild.owner or "Unknown"
    created_at = guild.created_at.strftime("%b %d, %Y • %H:%M")
    role_count = len(guild.roles)
    boost_count = guild.premium_subscription_count or 0
    boost_tier = guild.premium_tier

    # Embed setup
    embed = discord.Embed(
        title=f"🏰 Server Information — {guild.name}",
        color=discord.Color.blurple(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=guild.icon.url if guild.icon else discord.Embed.Empty)

    # ─── SERVER OVERVIEW ───────────────────────────────
    overview = (
        f"**• Server Name:** {guild.name}\n"
        f"**• Identifier:** `{guild.id}`\n"
        f"**• Created On:** {created_at}\n"
        f"**• Owner:** {owner.mention if hasattr(owner, 'mention') else owner}"
    )
    embed.add_field(name="🧾 SERVER OVERVIEW", value=overview, inline=False)

    # Space / Separator
    embed.add_field(name="\u200b", value="──────────────────────────────", inline=False)

    # ─── SERVER DETAILS ───────────────────────────────
    details = (
        f"**• Total Members:** {guild.member_count}\n"
        f"**• Channels:** {len(guild.channels)} (💬 {len(guild.text_channels)} text • 🔊 {len(guild.voice_channels)} voice)\n"
        f"**• Roles:** {role_count}\n"
        f"**• Boosts:** {boost_count} (Level {boost_tier})\n"
        f"**• Locale:** {guild.preferred_locale.replace('_', '-').title()}"
    )
    embed.add_field(name="🏗️ SERVER DETAILS", value=details, inline=False)

    # Space / Separator
    embed.add_field(name="\u200b", value="──────────────────────────────", inline=False)

    # ─── ACTIVITY ───────────────────────────────
    activity_info = f"**• Most Active Channel:** {active_channel.mention if active_channel else 'N/A'}"
    embed.add_field(name="📊 ACTIVITY", value=activity_info, inline=False)

    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )
    await ctx.send(embed=embed)


@bot.command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    """Displays detailed and well-formatted user information."""
    member = member or ctx.author

    # Roles (excluding @everyone)
    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
    role_count = len(roles)

    # Embed setup
    embed = discord.Embed(
        title=f"👤 User Information — {member.display_name}",
        color=discord.Color.orange(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # ─── USER INFO SECTION ────────────────────────────────
    user_info = (
        f"**• Username / Pseudonym:** {member.name}#{member.discriminator}\n"
        f"**• Identifier:** `{member.id}`\n"
        f"**• Account Created On:** {member.created_at.strftime('%b %d, %Y • %H:%M')}\n"
    )
    embed.add_field(name="🧾 USER INFO", value=user_info, inline=False)

    # ─── MEMBER INFO SECTION ───────────────────────────────
    member_info = (
        f"**• Joined Server:** {member.joined_at.strftime('%b %d, %Y • %H:%M')}\n"
        f"**• Roles ({role_count}):** {', '.join(roles) if roles else 'No roles'}\n"
        f"**• Highest Role:** {member.top_role.mention}\n"
        f"**• Status:** {str(member.status).title()}"
    )
    embed.add_field(name="🏠 MEMBER INFO", value=member_info, inline=False)

    # Footer
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)


# -----Say Command-----
@bot.command()
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message):
    """Bot repeats your message."""
    await ctx.message.delete()
    await ctx.send(message)


# ----Clear Command-----
@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Deleted {amount} messages.", delete_after=5)


# ---------------- General Commands ----------------
# ---------------- General Commands ----------------
# ---------------- General Commands ----------------
# ---------------- General Commands ----------------
# ---------------- General Commands ----------------
# ---------------- General Commands ----------------


# ---------------- GLOBAL ERROR HANDLER ----------------
@bot.event
async def on_command_error(ctx, error):
    # Unwrap CommandInvokeError to find root cause
    orig = getattr(error, "original", error)

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use that command.")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing argument: `{error.param}`")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Bad argument. Check command usage.")
        return
    if isinstance(error, commands.CommandNotFound):
        # silently ignore or optionally reply
        return
    # For everything else, log stack trace and inform owner/channel
    tb = "".join(traceback.format_exception(type(orig), orig, orig.__traceback__))
    print(f"Unhandled command error:\n{tb}")
    # try to send a short message to the channel
    try:
        await ctx.send(
            "⚠️ An unexpected error occurred. The developer has been notified."
        )
    except:
        pass
    # optionally send full trace to mod-log channel if exists:
    modlog = discord.utils.get(ctx.guild.text_channels, name="mod-log")
    if modlog:
        # trim to a reasonable length
        short = tb if len(tb) < 1900 else tb[-1900:]
        await modlog.send(
            f"🚨 Error in command `{ctx.command}` by {ctx.author.mention}:\n```py\n{short}\n```"
        )


# ==================== MODERATION COMMANDS ====================

# ==================== MODERATION COMMANDS ====================
# ==================== MODERATION COMMANDS ====================
# ==================== MODERATION COMMANDS ====================
# ==================== MODERATION COMMANDS ====================
# ==================== MODERATION COMMANDS ====================
# ==================== MODERATION COMMANDS ====================
# ==================== MODERATION COMMANDS ====================

# Dictionary to track warnings
async def mod_log(
    guild: discord.Guild, title: str, description: str, author: discord.Member = None
):
    ch = discord.utils.get(guild.text_channels, name="mod-log")
    embed = discord.Embed(
        title=title, description=description, color=discord.Color.red()
    )
    if author:
        embed.set_author(name=str(author), icon_url=author.display_avatar.url)
    if ch:
        await ch.send(embed=embed)


warns = {}

# ---------- Kick Command ----------
MOD_LOG_CHANNEL_ID = 1422329487227355366  # Replace with your mod-log channel ID


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    """Kick a member from the server with DM and mod-log."""

    if member == ctx.author:
        return await ctx.send("❌ You cannot kick yourself.")
    if member == ctx.guild.me:
        return await ctx.send("❌ I cannot kick myself.")
    if member.top_role >= ctx.author.top_role:
        return await ctx.send("❌ You cannot kick someone with an equal or higher role.")

    try:
        # DM before kicking
        try:
            await member.send(
                f"⚠️ You have been kicked from **{ctx.guild.name}**.\nReason: {reason}"
            )
        except:
            pass

        await member.kick(reason=reason)
    except discord.Forbidden:
        return await ctx.send(f"❌ I do not have permission to kick {member}.")
    except discord.HTTPException:
        return await ctx.send(f"❌ Failed to kick {member} due to an unexpected error.")

    embed = discord.Embed(
        title="👢 Member Kicked",
        color=discord.Color.orange(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    embed.add_field(
        name="Kicked by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)


# ---------- Ban ----------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    """Ban a member from the server with DM and mod-log."""

    if member == ctx.author:
        return await ctx.send("❌ You cannot ban yourself.")
    if member == ctx.guild.me:
        return await ctx.send("❌ I cannot ban myself.")
    if member.top_role >= ctx.author.top_role:
        return await ctx.send("❌ You cannot ban someone with an equal or higher role.")

    try:
        # DM before banning
        try:
            await member.send(
                f"🔨 You have been banned from **{ctx.guild.name}**.\nReason: {reason}"
            )
        except:
            pass

        await member.ban(reason=reason)
    except discord.Forbidden:
        return await ctx.send(f"❌ I do not have permission to ban {member}.")
    except discord.HTTPException:
        return await ctx.send(f"❌ Failed to ban {member} due to an unexpected error.")

    embed = discord.Embed(
        title="🔨 Member Banned",
        color=discord.Color.red(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    embed.add_field(
        name="Banned by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)


# ---------- Unban ----------
@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user: str, *, reason="No reason provided"):
    """
    Unban a member by ID or Username#Discriminator with DM and mod-log.
    Usage: !unban 123456789012345678
           !unban SomeUser#1234
    """
    banned_user = None
    async for ban_entry in ctx.guild.bans():
        # Match by ID
        if user.isdigit() and int(user) == ban_entry.user.id:
            banned_user = ban_entry.user
            break
        # Match by username#discriminator
        elif (
            user.lower()
            == f"{ban_entry.user.name}#{ban_entry.user.discriminator}".lower()
        ):
            banned_user = ban_entry.user
            break

    if banned_user is None:
        return await ctx.send(f"❌ No banned user found matching `{user}`.")

    try:
        await ctx.guild.unban(banned_user, reason=reason)

        # DM after unban
        try:
            await banned_user.send(
                f"✅ You have been unbanned from **{ctx.guild.name}**.\nReason: {reason}"
            )
        except:
            pass
    except discord.Forbidden:
        return await ctx.send(f"❌ I do not have permission to unban {banned_user}.")
    except discord.HTTPException:
        return await ctx.send(
            f"❌ Failed to unban {banned_user} due to an unexpected error."
        )

    embed = discord.Embed(
        title="🟢 Member Unbanned",
        color=discord.Color.green(),
        timestamp=ctx.message.created_at,
    )
    embed.add_field(
        name="Member", value=f"{banned_user} ({banned_user.id})", inline=False
    )
    embed.add_field(
        name="Unbanned by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)


# ---------- Warn Checks----------
user_warnings = {}  # {guild_id: {user_id: [list of reasons]}}
# ---------- Warn ----------
@bot.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    """Warn a member in the server with DM and mod-log."""

    # Prevent self-warn or bot-warn
    if member == ctx.author:
        return await ctx.send("❌ You cannot warn yourself.")
    if member == ctx.guild.me:
        return await ctx.send("❌ I cannot warn myself.")
    if member.top_role >= ctx.author.top_role:
        return await ctx.send("❌ You cannot warn someone with an equal or higher role.")

    # Initialize guild warnings
    guild_warns = user_warnings.setdefault(ctx.guild.id, {})
    member_warns = guild_warns.setdefault(member.id, [])

    # Add the warning
    member_warns.append(reason)

    # DM the member
    try:
        await member.send(
            f"⚠️ You have been warned in **{ctx.guild.name}**.\nReason: {reason}\nTotal warnings: {len(member_warns)}"
        )
    except:
        pass  # Ignore if DMs are closed

    # Embed for public/mod-log
    embed = discord.Embed(
        title="⚠️ Member Warned",
        color=discord.Color.orange(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    embed.add_field(
        name="Warned by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=str(len(member_warns)), inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)


# Optional: Check Warnings Command
@bot.command(name="checkwarnings")
@commands.has_permissions(kick_members=True)
async def check_warnings(ctx, member: discord.Member):
    """Check how many warnings a member has."""
    guild_warns = user_warnings.get(ctx.guild.id, {})
    member_warns = guild_warns.get(member.id, [])

    await ctx.send(
        f"📋 {member} has {len(member_warns)} warning(s).\n"
        f"Reasons: {member_warns if member_warns else 'None'}"
    )


# ---------- Clear Warnings ----------
@bot.command()
@commands.has_permissions(kick_members=True)
async def clearwarn(ctx, member: discord.Member):
    """Clear all warnings for a member."""
    if member.id in warns:
        warns.pop(member.id)
        await ctx.send(f"✅ Warnings for {member.mention} have been cleared.")
    else:
        await ctx.send(f"ℹ️ {member.mention} has no warnings.")


# ---------- Mute ----------
@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason="No reason provided"):
    """Mute a member in the server with DM and mod-log."""

    # Prevent self-mute or bot mute
    if member == ctx.author:
        return await ctx.send("❌ You cannot mute yourself.")
    if member == ctx.guild.me:
        return await ctx.send("❌ I cannot mute myself.")
    if member.top_role >= ctx.author.top_role:
        return await ctx.send("❌ You cannot mute someone with an equal or higher role.")

    # Get or create "Muted" role
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        # Optionally create the role automatically
        try:
            muted_role = await ctx.guild.create_role(
                name="Muted",
                permissions=discord.Permissions(send_messages=False, speak=False),
                reason="Muted role needed for muting members",
            )
            # Apply role to all text channels
            for channel in ctx.guild.channels:
                await channel.set_permissions(
                    muted_role, send_messages=False, speak=False
                )
        except Exception as e:
            return await ctx.send(f"❌ Could not create Muted role: {e}")

    if muted_role in member.roles:
        return await ctx.send(f"⚠️ {member.mention} is already muted.")

    try:
        await member.add_roles(muted_role, reason=reason)

        # DM notification
        try:
            await member.send(
                f"🔇 You have been muted in **{ctx.guild.name}**.\nReason: {reason}"
            )
        except:
            pass

    except discord.Forbidden:
        return await ctx.send(f"❌ I do not have permission to mute {member}.")
    except discord.HTTPException:
        return await ctx.send(f"❌ Failed to mute {member} due to an unexpected error.")

    # Embed
    embed = discord.Embed(
        title="🔇 Member Muted",
        color=discord.Color.dark_gray(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    embed.add_field(
        name="Muted by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)


# --------------------------Temporary mute command------------------
temp_mutes = {}  # {guild_id: {user_id: datetime_end}}


@bot.command()
@commands.has_permissions(manage_roles=True)
async def tempmute(
    ctx, member: discord.Member, duration: int, *, reason="No reason provided"
):
    """
    Temporarily mute a member.
    Duration is in minutes.
    """
    if (
        member == ctx.author
        or member == ctx.guild.me
        or member.top_role >= ctx.author.top_role
    ):
        return await ctx.send("❌ You cannot mute this member.")

    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        return await ctx.send("❌ Muted role does not exist. Please create it first.")
    if muted_role in member.roles:
        return await ctx.send(f"⚠️ {member.mention} is already muted.")

    await member.add_roles(muted_role, reason=reason)

    # Store tempmute end time immediately
    end_time = datetime.utcnow() + timedelta(minutes=duration)
    guild_mutes = temp_mutes.setdefault(ctx.guild.id, {})
    guild_mutes[member.id] = end_time

    # DM
    try:
        await member.send(
            f"🔇 You have been muted in **{ctx.guild.name}** for {duration} minutes.\nReason: {reason}"
        )
    except:
        pass

    # Embed
    embed = discord.Embed(
        title="🔇 Temporary Mute",
        color=discord.Color.dark_gray(),
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    embed.add_field(
        name="Muted by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )
    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)

    # Unmute after duration
    async def unmute_task():
        await asyncio.sleep(duration * 60)
        if muted_role in member.roles:
            await member.remove_roles(muted_role, reason="Temporary mute expired")
            del guild_mutes[member.id]  # remove tracking

            # Unmute embed
            unmute_embed = discord.Embed(
                title="✅ Temporary Mute Expired",
                color=discord.Color.green(),
                timestamp=datetime.utcnow(),
            )
            unmute_embed.add_field(
                name="Member", value=f"{member} ({member.id})", inline=False
            )
            unmute_embed.add_field(
                name="Reason", value="Temporary mute expired", inline=False
            )
            await ctx.send(embed=unmute_embed)
            if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
                await mod_log.send(embed=unmute_embed)

    bot.loop.create_task(unmute_task())


# ------------------- CHECK MUTE TIME -------------------
@bot.command()
async def mutetime(ctx, member: discord.Member = None):
    """Check remaining mute time. Defaults to yourself if no member mentioned."""
    member = member or ctx.author
    guild_mutes = temp_mutes.get(ctx.guild.id, {})
    end_time = guild_mutes.get(member.id)

    if not end_time:
        if member == ctx.author:
            return await ctx.send("✅ You are not currently temporarily muted.")
        else:
            return await ctx.send(f"✅ {member} is not currently temporarily muted.")

    remaining = end_time - datetime.utcnow()
    if remaining.total_seconds() <= 0:
        del guild_mutes[member.id]
        return await ctx.send(f"✅ {member}'s temporary mute has already expired.")

    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    if member == ctx.author:
        await ctx.send(
            f"⏱ You have **{hours}h {minutes}m {seconds}s** left on your temporary mute."
        )
    else:
        await ctx.send(
            f"⏱ {member} has **{hours}h {minutes}m {seconds}s** left on their temporary mute."
        )


# ---------- Unmute ----------
@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member, *, reason="No reason provided"):
    """Unmute a member in the server with DM and mod-log."""

    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role or muted_role not in member.roles:
        return await ctx.send(f"⚠️ {member.mention} is not muted.")

    try:
        await member.remove_roles(muted_role, reason=reason)

        # DM notification
        try:
            await member.send(
                f"✅ You have been unmuted in **{ctx.guild.name}**.\nReason: {reason}"
            )
        except:
            pass

    except discord.Forbidden:
        return await ctx.send(f"❌ I do not have permission to unmute {member}.")
    except discord.HTTPException:
        return await ctx.send(
            f"❌ Failed to unmute {member} due to an unexpected error."
        )

    # Embed
    embed = discord.Embed(
        title="✅ Member Unmuted",
        color=discord.Color.green(),
        timestamp=ctx.message.created_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    embed.add_field(
        name="Unmuted by", value=f"{ctx.author} ({ctx.author.id})", inline=False
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(
        text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

    # Mod-log
    mod_log = ctx.guild.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_log and mod_log.permissions_for(ctx.guild.me).send_messages:
        await mod_log.send(embed=embed)


# ---------- Softban ----------
@bot.command()
@commands.has_permissions(ban_members=True)
async def softban(ctx, member: discord.Member, *, reason="No reason provided"):
    """Softban a member (ban and unban to delete messages)."""
    await member.ban(reason=reason, delete_message_days=7)
    await member.unban(reason="Softban complete")
    await ctx.send(
        f"🧹 {member.mention} was softbanned. Messages deleted. Reason: {reason}"
    )


# ---------- Lockdown ----------
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lockdown(ctx, channel: discord.TextChannel = None):
    """Lock a text channel to prevent sending messages."""
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"🔒 {channel.mention} is now locked.")


# ---------- Unlock ----------
@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    """Unlock a previously locked channel."""
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"🔓 {channel.mention} is now unlocked.")


# ---------- Nickname Change ----------
@bot.command()
@commands.has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, nickname):
    """Change a member's nickname."""
    await member.edit(nick=nickname)
    await ctx.send(f"✏️ Changed nickname of {member.mention} to **{nickname}**")


# ---------- Role Management ----------
@bot.command()
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member, role: discord.Role):
    """Add a role to a member."""
    await member.add_roles(role)
    await ctx.send(f"✅ Added role {role.name} to {member.mention}")


@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member, role: discord.Role):
    """Remove a role from a member."""
    await member.remove_roles(role)
    await ctx.send(f"❌ Removed role {role.name} from {member.mention}")


# ---------- Announcement ----------
@bot.command()
@commands.has_permissions(administrator=True)
async def announce(ctx, *, message):
    """Send an announcement to the current channel."""
    embed = discord.Embed(
        title="📢 Announcement", description=message, color=discord.Color.blue()
    )
    await ctx.send(embed=embed)


# ---Purge Bot Messages Only---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def purgebot(ctx, amount: int = 10):
    """Delete bot messages only in the channel."""
    deleted = await ctx.channel.purge(
        limit=amount, check=lambda m: m.author == ctx.bot.user
    )
    await ctx.send(f"🧹 Deleted {len(deleted)} bot messages.", delete_after=5)


# ---------- View Member Warnings ----------
@bot.command()
@commands.has_permissions(kick_members=True)
async def warnings(ctx, member: discord.Member):
    """View warnings for a member."""
    count = warns.get(member.id, 0)
    await ctx.send(f"⚠️ {member.mention} has {count} warning(s).")


# ---------- Set Slowmode ----------
@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, channel: discord.TextChannel, seconds: int):
    try:
        await channel.edit(slowmode_delay=seconds)
        await ctx.send(f"✅ Slowmode set to `{seconds}` seconds in {channel.mention}")
    except discord.Forbidden:
        await ctx.send("❌ I don’t have permission to edit this channel.")


# ---------- Announcement with Embed ----------
@bot.command(name="announce_embed")
@commands.has_permissions(administrator=True)
async def announce(ctx, channel: discord.TextChannel, *, message: str):
    embed = discord.Embed(
        title="📢 Announcement", description=message, color=discord.Color.gold()
    )
    embed.set_footer(text=f"By {ctx.author}")
    await channel.send(embed=embed)
    await ctx.send(f"✅ Announcement sent to {channel.mention}")


# ---------- Temporary Role Assignment ----------
@bot.command(name="temprole")
@commands.has_permissions(manage_roles=True)
async def temprole(ctx, member: discord.Member, role: discord.Role, time: int = 60):
    await member.add_roles(role, reason=f"Temporary role by {ctx.author}")
    await ctx.send(f"✅ Added role {role.name} to {member.mention} for {time} seconds.")

    await asyncio.sleep(time)
    await member.remove_roles(role, reason="Temporary role expired")
    await ctx.send(f"⏳ Role {role.name} removed from {member.mention}")


# ---------- Mass Role Assignment ----------
@bot.command(name="massrole")
@commands.has_permissions(administrator=True)
async def massrole(ctx, role: discord.Role):
    added = 0
    for member in ctx.guild.members:
        if role not in member.roles:
            try:
                await member.add_roles(role)
                added += 1
            except discord.Forbidden:
                continue
    await ctx.send(f"✅ Role {role.name} given to {added} members.")


# ---------- Role Info ----------
@bot.command(name="roleinfo")
async def roleinfo(ctx, role: discord.Role):
    members = [member.mention for member in role.members]
    embed = discord.Embed(title=f"ℹ️ Role Info: {role.name}", color=role.color)
    embed.add_field(name="ID", value=role.id, inline=False)
    embed.add_field(name="Color", value=str(role.color), inline=False)
    embed.add_field(
        name="Members", value=", ".join(members) if members else "None", inline=False
    )
    embed.add_field(
        name="Permissions",
        value=", ".join([perm[0] for perm in role.permissions if perm[1]]),
        inline=False,
    )
    await ctx.send(embed=embed)


####### Reaction Roles #######

# --------------------------
# Load / Save Reaction Roles
# --------------------------
# --------------------------
# File Storage
# --------------------------
DATA_FILE = "reaction_roles.json"


def load_reaction_roles():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_reaction_roles():
    with open(DATA_FILE, "w") as f:
        json.dump(reaction_roles, f, indent=4)


reaction_roles = load_reaction_roles()

# --------------------------
# Reaction Role Command Group
# --------------------------
@bot.group(name="reactionrole", invoke_without_command=True)
@commands.has_permissions(manage_roles=True)
async def reactionrole(ctx):
    """Base command for reaction roles."""
    await ctx.send(
        "⚙️ Use one of the subcommands: `add`, `list`, `remove`, or `clear`.\nExample: `!reactionrole add <message_id> <emoji> <role>`"
    )


# --------------------------
# ADD
# --------------------------
@reactionrole.command(name="add")
async def rr_add(ctx, message_id: int, emoji: str, role: discord.Role):
    """Add a reaction role to a message."""
    try:
        message = await ctx.channel.fetch_message(message_id)
        await message.add_reaction(emoji)

        # Save reaction role data
        if str(message_id) not in reaction_roles:
            reaction_roles[str(message_id)] = {}

        reaction_roles[str(message_id)][emoji] = role.id
        save_reaction_roles()

        await ctx.send(f"✅ Reaction role added: {emoji} → {role.name}", delete_after=6)

    except discord.NotFound:
        await ctx.send("❌ Message not found.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("❌ Missing permission to react or manage roles.", delete_after=5)
    except Exception as e:
        await ctx.send(f"⚠️ Error: {e}", delete_after=5)


# --------------------------
# LIST
# --------------------------
@reactionrole.command(name="list")
async def rr_list(ctx):
    """List all configured reaction roles."""
    if not reaction_roles:
        await ctx.send("📭 No reaction roles have been set yet.")
        return

    embed = discord.Embed(
        title="🎭 Reaction Role Configurations", color=discord.Color.blurple()
    )

    for msg_id, mapping in reaction_roles.items():
        value = "\n".join(
            [f"{emoji} → <@&{role_id}>" for emoji, role_id in mapping.items()]
        )
        embed.add_field(name=f"Message ID: {msg_id}", value=value, inline=False)

    await ctx.send(embed=embed)


# --------------------------
# REMOVE
# --------------------------
@reactionrole.command(name="remove")
async def rr_remove(ctx, message_id: int, emoji: str):
    """Remove a specific emoji from a message’s reaction roles."""
    msg_id = str(message_id)

    if msg_id in reaction_roles and emoji in reaction_roles[msg_id]:
        del reaction_roles[msg_id][emoji]

        # If message has no roles left, remove the message ID entirely
        if not reaction_roles[msg_id]:
            del reaction_roles[msg_id]

        save_reaction_roles()
        await ctx.send(
            f"❌ Removed reaction role for {emoji} on message `{message_id}`.",
            delete_after=6,
        )
    else:
        await ctx.send(
            "⚠️ Couldn’t find that emoji or message ID in the database.", delete_after=5
        )


#   --------------------------
# role MEMBER UPDATE EVENT
@bot.event
async def on_member_update(before, after):
    """Detect when roles are added or removed, DM the user, and log the event."""
    try:
        # Get roles before and after
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        # Detect added and removed roles
        added_roles = [r for r in after_roles if r not in before_roles]
        removed_roles = [r for r in before_roles if r not in after_roles]

        if not added_roles and not removed_roles:
            return  # No role changes

        # Get log channel (replace with your actual log channel ID)
        log_channel_id = 1422329487227355366  # 🔧 CHANGE THIS
        log_channel = bot.get_channel(log_channel_id)

        # Prepare text for DM and log
        added_names = ", ".join([r.name for r in added_roles]) if added_roles else None
        removed_names = (
            ", ".join([r.name for r in removed_roles]) if removed_roles else None
        )

        # --------------------------
        # 💬 Send DM to the member
        # --------------------------
        try:
            msg_lines = [f"👋 Hello {after.display_name},"]
            if added_names:
                msg_lines.append(
                    f"✅ You’ve been **given** the following role(s): {added_names}"
                )
            if removed_names:
                msg_lines.append(
                    f"❌ The following role(s) were **removed**: {removed_names}"
                )
            msg_lines.append(f"\nFrom **{after.guild.name}** server.")
            await after.send("\n".join(msg_lines))
        except discord.Forbidden:
            if log_channel:
                await log_channel.send(f"📪 Could not DM **{after}** (DMs closed).")

        # --------------------------
        # 🧾 Log to moderation channel
        # --------------------------
        if log_channel:
            embed = discord.Embed(
                title="🧩 Role Change Logged",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="👤 Member", value=f"{after.mention} ({after.id})", inline=False
            )
            if added_names:
                embed.add_field(name="✅ Roles Added", value=added_names, inline=False)
            if removed_names:
                embed.add_field(
                    name="❌ Roles Removed", value=removed_names, inline=False
                )
            embed.set_footer(text=f"Guild: {after.guild.name}")
            await log_channel.send(embed=embed)

    except Exception as e:
        print(f"⚠️ Error in on_member_update: {e}")


# --------------------------
# CLEAR
# --------------------------
@reactionrole.command(name="clear")
async def rr_clear(ctx, message_id: int):
    """Clear all reaction roles for a specific message."""
    msg_id = str(message_id)

    if msg_id in reaction_roles:
        del reaction_roles[msg_id]
        save_reaction_roles()
        await ctx.send(
            f"🧹 All reaction roles for message `{message_id}` cleared!", delete_after=6
        )
    else:
        await ctx.send(
            "⚠️ That message doesn’t have any reaction roles set.", delete_after=5
        )


# --------------------------
# Reaction Add Event
# --------------------------
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.message_id) in reaction_roles:
        emoji = str(payload.emoji)
        role_id = reaction_roles[str(payload.message_id)].get(emoji)
        if not role_id:
            return

        guild = bot.get_guild(payload.guild_id)
        role = guild.get_role(role_id)
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        try:
            await member.add_roles(role)
            try:
                await member.send(
                    f"✅ You’ve been given the **{role.name}** role in **{guild.name}**!"
                )
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            print(
                f"⚠️ Missing permission to add role {role.name} to {member.display_name}"
            )


# --------------------------
# Reaction Remove Event
# --------------------------
@bot.event
async def on_raw_reaction_remove(payload):
    if str(payload.message_id) in reaction_roles:
        emoji = str(payload.emoji)
        role_id = reaction_roles[str(payload.message_id)].get(emoji)
        if not role_id:
            return

        guild = bot.get_guild(payload.guild_id)
        role = guild.get_role(role_id)
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        try:
            await member.remove_roles(role)
            try:
                await member.send(
                    f"❎ The **{role.name}** role has been removed in **{guild.name}**."
                )
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            print(
                f"⚠️ Missing permission to remove role {role.name} from {member.display_name}"
            )


# ---------------- Role & Channel Management ----------------

# Delete a role
@bot.command(name="deleterole")
@commands.has_permissions(manage_roles=True)
async def deleterole(ctx, *, role_name: str):
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role:
        try:
            await role.delete(reason=f"Deleted by {ctx.author}")
            await ctx.send(f"✅ Role **{role_name}** has been deleted.")
        except discord.Forbidden:
            await ctx.send("❌ I do not have permission to delete this role.")
    else:
        await ctx.send(f"❌ Role **{role_name}** not found.")


# Delete a channel
@bot.command(name="deletechannel")
@commands.has_permissions(manage_channels=True)
async def deletechannel(ctx, *, channel_name: str):
    channel = discord.utils.get(ctx.guild.channels, name=channel_name)
    if channel:
        try:
            await channel.delete(reason=f"Deleted by {ctx.author}")
            await ctx.send(f"✅ Channel **{channel_name}** has been deleted.")
        except discord.Forbidden:
            await ctx.send("❌ I do not have permission to delete this channel.")
    else:
        await ctx.send(f"❌ Channel **{channel_name}** not found.")


# Rename a channel
@bot.command(name="renamechannel")
@commands.has_permissions(manage_channels=True)
async def renamechannel(ctx, old_name: str, *, new_name: str):
    channel = discord.utils.get(ctx.guild.channels, name=old_name)
    if channel:
        try:
            await channel.edit(name=new_name, reason=f"Renamed by {ctx.author}")
            await ctx.send(f"✅ Channel **{old_name}** renamed to **{new_name}**.")
        except discord.Forbidden:
            await ctx.send("❌ I do not have permission to rename this channel.")
    else:
        await ctx.send(f"❌ Channel **{old_name}** not found.")


# Rename a role
@bot.command(name="renamerole")
@commands.has_permissions(manage_roles=True)
async def renamerole(ctx, old_name: str, *, new_name: str):
    role = discord.utils.get(ctx.guild.roles, name=old_name)
    if role:
        try:
            await role.edit(name=new_name, reason=f"Renamed by {ctx.author}")
            await ctx.send(f"✅ Role **{old_name}** renamed to **{new_name}**.")
        except discord.Forbidden:
            await ctx.send("❌ I do not have permission to rename this role.")
    else:
        await ctx.send(f"❌ Role **{old_name}** not found.")

    # ----- Channels button------
    @discord.ui.button(label="📁 Channels", style=discord.ButtonStyle.secondary)
    async def channels(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        categories = {
            "Info": ["📜rules", "📢announcements", "ℹ️info"],
            "Gaming": ["💬general", "🤣memes", "📹clips"],
            "Voice": ["🔊Lobby", "🎤VC 1", "🎧VC 2"],
        }
        created_channels = []
        for cat_name, channels in categories.items():
            category = discord.utils.get(interaction.guild.categories, name=cat_name)
            if not category:
                category = await interaction.guild.create_category(cat_name)
            for ch_name in channels:
                ch = discord.utils.get(interaction.guild.channels, name=ch_name)
                if not ch:
                    if "VC" in ch_name or "🔊" in ch_name:
                        await interaction.guild.create_voice_channel(
                            ch_name, category=category
                        )
                    else:
                        await interaction.guild.create_text_channel(
                            ch_name, category=category
                        )
                    created_channels.append(ch_name)
        await interaction.response.send_message(
            f"✅ Channels created: {', '.join(created_channels)}", ephemeral=True
        )

    # Finish button
    @discord.ui.button(label="✅ Finish Setup", style=discord.ButtonStyle.success)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🎉 Setup complete! Your server is ready.", ephemeral=True
        )
        self.stop()


# ---------------- CREATE CHANNEL, ROLES, VC, WITH INTERACTIVE PROMPTS ----------------


@bot.command(name="create")
@commands.has_permissions(administrator=True)
async def create(ctx):
    # Step 1: Ask what to create
    options = ["text", "voice", "category", "role"]
    await ctx.send("⚙️ What would you like to create? (text / voice / category / role)")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    msg = await bot.wait_for("message", check=check, timeout=30)
    choice = msg.content.lower()

    if choice not in options:
        return await ctx.send(
            "❌ Invalid choice. Please choose text/voice/category/role."
        )

    # Step 2: Ask for name
    await ctx.send(f"✏️ Enter a name for the new {choice}:")
    msg = await bot.wait_for("message", check=check, timeout=30)
    name = msg.content

    # Step 3: Create
    if choice == "text":
        await ctx.guild.create_text_channel(name)
        await ctx.send(f"✅ Created text channel **{name}**")

    elif choice == "voice":
        await ctx.guild.create_voice_channel(name)
        await ctx.send(f"✅ Created voice channel **{name}**")

    elif choice == "category":
        await ctx.guild.create_category(name)
        await ctx.send(f"✅ Created category **{name}**")

    elif choice == "role":
        await ctx.guild.create_role(name=name)
        await ctx.send(f"✅ Created role **{name}**")


@create.error
async def create_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You must be an **Administrator** to use this command.")


# ---------------- DYNAMIC ROLE COMMAND ----------------
@bot.command(
    name="add_role",
)
@commands.has_permissions(administrator=True)
async def add_role(ctx, *, role_name: str):
    """Create a role with a custom name"""
    guild = ctx.guild
    existing_role = discord.utils.get(guild.roles, name=role_name)

    if existing_role:
        await ctx.send(f"⚠️ Role `{role_name}` already exists.")
        return

    await guild.create_role(name=role_name)
    await ctx.send(f"✅ Role `{role_name}` has been created!")


# ---------------- DYNAMIC TEXT CHANNEL COMMAND ----------------
@bot.command(name="addtext")
@commands.has_permissions(administrator=True)
async def add_text_channel(ctx, *, channel_name: str):
    """Create a text channel with a custom name"""
    guild = ctx.guild
    existing_channel = discord.utils.get(guild.text_channels, name=channel_name)

    if existing_channel:
        await ctx.send(f"⚠️ Text channel `{channel_name}` already exists.")
        return

    await guild.create_text_channel(channel_name)
    await ctx.send(f"✅ Text channel `{channel_name}` has been created!")


# ---------------- DYNAMIC VOICE CHANNEL COMMAND ----------------
@bot.command(name="addvoice")
@commands.has_permissions(administrator=True)
async def add_voice_channel(ctx, *, channel_name: str):
    """Create a voice channel with a custom name"""
    guild = ctx.guild
    existing_channel = discord.utils.get(guild.voice_channels, name=channel_name)

    if existing_channel:
        await ctx.send(f"⚠️ Voice channel `{channel_name}` already exists.")
        return

    await guild.create_voice_channel(channel_name)
    await ctx.send(f"✅ Voice channel `{channel_name}` has been created!")


import asyncio
import json
import os

# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------------- INTERACTIVE SERVER SETUP WIZARD ----------------
# ---------- Server Setup System (Hybrid) ----------
import discord
from discord.ext import commands

SETUP_DATA = "setup_sessions.json"
TEMPLATES_FILE = "server_templates.json"
LOG_CHANNEL_NAME = "admin-mod-logs"  # created automatically if missing
DEFAULT_ROLES = [
    "@everyone",
    "Newbie",
    "Member",
    "Moderator",
    "Admin",
]  # bot will create if missing (except @everyone)

# --- helpers to persist sessions + templates ---
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


setup_sessions = load_json(SETUP_DATA)  # keyed by guild_id (str)
templates = load_json(TEMPLATES_FILE)  # can be prefilled with templates


def save_sessions():
    save_json(SETUP_DATA, setup_sessions)


def save_templates():
    save_json(TEMPLATES_FILE, templates)


# --- utility functions ---
def is_cancel_or_stop(msg_content: str):
    return msg_content.strip().lower() in ("cancel", "stop", "abort")


async def ensure_role_exists(guild: discord.Guild, role_name: str):
    """Return a Role object; create if doesn't exist (except @everyone)."""
    role_name = role_name.strip()
    if role_name == "@everyone":
        return guild.default_role
    # try mention or ID
    # try by exact name first
    role = discord.utils.find(lambda r: r.name == role_name, guild.roles)
    if role:
        return role
    # try by id if numeric
    if role_name.isdigit():
        r = guild.get_role(int(role_name))
        if r:
            return r
    # create role
    try:
        new_role = await guild.create_role(name=role_name)
        return new_role
    except discord.Forbidden:
        return None


def role_names_to_ids(guild: discord.Guild, names_list):
    """Convert list of names (strings) to list of role IDs (create roles if needed)."""
    found = []
    for name in names_list:
        name = name.strip()
        if not name:
            continue
        r = discord.utils.find(lambda rr: rr.name == name, guild.roles)
        if r:
            found.append(r.id)
        else:
            # create role
            # Warning: creation needs Manage Roles permission
            # We'll return None to indicate creation required by wizard, handled there
            found.append(name)  # keep as name to be created later
    return found


def overwrite_from_choice(guild, role_id_or_name, allow_send=True, allow_view=True):
    """Create a permission overwrite object for a role object or name (role may not exist)."""
    # This will be used at creation time where role objects will exist
    perm = discord.PermissionOverwrite()
    perm.view_channel = allow_view
    # for text channels, control send_messages
    perm.send_messages = allow_send
    return perm


# --- setup command group ---
@bot.group(name="setup", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def setup_group(ctx):
    """Base group for modular setup commands. Use `!setupserver` for guided wizard."""
    await ctx.send(
        "Use `!setupserver` for guided server setup, or one of the subcommands: `addrole`, `addcategory`, `addchannel`, `permissions`, `summary`, `confirm`, `cancel`, `template`."
    )


# ---------- Guided wizard with auto-resume ----------
@bot.command(name="setupserver")
@commands.has_permissions(administrator=True)
async def setupserver(ctx):
    """
    Start or resume the interactive server setup wizard.
    Sessions are persisted in setup_sessions.json so they can be resumed after bot restarts.
    """
    guild_id = str(ctx.guild.id)
    author = ctx.author

    # if there's an existing unfinished session, ask whether to resume
    if guild_id in setup_sessions and not setup_sessions[guild_id].get(
        "finished", False
    ):
        await ctx.send(
            f"🔁 An unfinished setup exists for this server. Do you want to resume it? (yes / no)"
        )
        try:
            msg = await bot.wait_for(
                "message",
                check=lambda m: m.author == author and m.channel == ctx.channel,
                timeout=60,
            )
            if msg.content.strip().lower() in ("yes", "y"):
                session = setup_sessions[guild_id]
                await ctx.send("⏳ Resuming previous setup...")
                await run_wizard(ctx, session, resume=True)
                return
            else:
                # drop old session
                del setup_sessions[guild_id]
                save_sessions()
                await ctx.send(
                    "🗑️ Old setup session discarded. Starting a fresh one..."
                )
        except asyncio.TimeoutError:
            return await ctx.send(
                "⌛ Timed out. Run `!setupserver` again to resume or start fresh."
            )

    # start new session object
    session = {
        "guild_id": ctx.guild.id,
        "creator_id": ctx.author.id,
        "roles": [],  # list of role names (created first)
        "categories": [],  # list of dicts: {name, text_channels:[], voice_channels:[], permissions: {role_name: {view, send}}}
        "log_channel": LOG_CHANNEL_NAME,
        "template": None,
        "finished": False,
    }
    setup_sessions[guild_id] = session
    save_sessions()

    await run_wizard(ctx, session, resume=False)


async def run_wizard(ctx, session, resume=False):
    """
    Core interactive flow. If resume=True, it will continue from current session state.
    """
    author = ctx.author
    guild: discord.Guild = ctx.guild
    gid = str(guild.id)

    def check(m):
        return m.author == author and m.channel == ctx.channel

    try:
        # ---------- Ensure log channel ----------
        log_channel = discord.utils.get(
            guild.text_channels, name=session.get("log_channel", LOG_CHANNEL_NAME)
        )
        if not log_channel:
            try:
                log_channel = await guild.create_text_channel(
                    session.get("log_channel", LOG_CHANNEL_NAME)
                )
                await log_channel.send("📝 Log channel created by setup wizard.")
            except discord.Forbidden:
                await ctx.send(
                    "⚠️ I cannot create the log channel. Please ensure I have Manage Channels permission."
                )
        # save nothing else, proceed

        # ---------- Ensure default roles exist ----------
        # Create roles if they don't exist yet (except @everyone)
        existing_roles = {r.name: r for r in guild.roles}
        for base in DEFAULT_ROLES:
            if base == "@everyone":
                continue
            if base not in existing_roles:
                try:
                    created = await guild.create_role(name=base)
                    existing_roles[created.name] = created
                    if log_channel:
                        await log_channel.send(
                            f"🆕 Created default role `{created.name}`"
                        )
                except discord.Forbidden:
                    await ctx.send(
                        f"⚠️ Missing permission to create default role `{base}`. Please create it manually or give the bot Manage Roles."
                    )
        # refresh roles list
        existing_roles = {r.name: r for r in guild.roles}

        # ---------- ROLES CREATION (first major step) ----------
        if not session["roles"]:
            await ctx.send(
                "🎭 **Step 1 — Roles**\nHow many roles would you like to create? (type a number, or 0 to skip)\nType `cancel` to abort."
            )
            msg = await bot.wait_for("message", check=check, timeout=120)
            if is_cancel_or_stop(msg.content):
                del setup_sessions[gid]
                save_sessions()
                return await ctx.send("❌ Setup cancelled.")
            try:
                num_roles = int(msg.content)
            except:
                return await ctx.send(
                    "❌ Invalid number. Start the wizard again with `!setupserver`."
                )
            if num_roles > 0:
                for i in range(num_roles):
                    await ctx.send(
                        f"📝 Enter a name for role **{i+1}/{num_roles}** (or type `cancel`):"
                    )
                    rmsg = await bot.wait_for("message", check=check, timeout=120)
                    if is_cancel_or_stop(rmsg.content):
                        del setup_sessions[gid]
                        save_sessions()
                        return await ctx.send("❌ Setup cancelled.")
                    session["roles"].append(rmsg.content.strip())
                    setup_sessions[gid] = session
                    save_sessions()
            else:
                await ctx.send("ℹ️ Skipping role creation (you can add roles later).")
        else:
            await ctx.send(
                "🎭 Roles already defined in session; skipping role creation step."
            )

        # Create roles now (some may exist already)
        created_role_objs = {}
        for role_name in session["roles"]:
            role = discord.utils.find(lambda r: r.name == role_name, guild.roles)
            if not role:
                try:
                    role = await guild.create_role(name=role_name)
                    if log_channel:
                        await log_channel.send(f"➕ Created role `{role_name}`")
                except discord.Forbidden:
                    await ctx.send(
                        f"⚠️ Missing permission to create role `{role_name}`. Please create it manually and re-run."
                    )
                    # continue trying others
                    continue
            created_role_objs[role_name] = role

        # ---------- CATEGORIES / CHANNELS ----------
        # Ask how many categories
        if not session["categories"]:
            await ctx.send(
                "📂 **Step 2 — Categories & Channels**\nHow many categories would you like to create? (0 to skip)"
            )
            msg = await bot.wait_for("message", check=check, timeout=120)
            if is_cancel_or_stop(msg.content):
                del setup_sessions[gid]
                save_sessions()
                return await ctx.send("❌ Setup cancelled.")
            try:
                num_cats = int(msg.content)
            except:
                return await ctx.send(
                    "❌ Invalid number. Start over with `!setupserver`."
                )
            for ci in range(num_cats):
                await ctx.send(
                    f"🗂️ Enter a name for category **{ci+1}/{num_cats}** (or `cancel`):"
                )
                name_msg = await bot.wait_for("message", check=check, timeout=120)
                if is_cancel_or_stop(name_msg.content):
                    del setup_sessions[gid]
                    save_sessions()
                    return await ctx.send("❌ Setup cancelled.")
                cat_name = name_msg.content.strip()
                cat_entry = {
                    "name": cat_name,
                    "text_channels": [],
                    "voice_channels": [],
                    "permissions": {},
                }  # permissions: role_name -> {view:bool, send:bool}
                # text channels
                await ctx.send(
                    f"💬 How many text channels under **{cat_name}**? (0 to skip)"
                )
                tmsg = await bot.wait_for("message", check=check, timeout=120)
                if is_cancel_or_stop(tmsg.content):
                    del setup_sessions[gid]
                    save_sessions()
                    return await ctx.send("❌ Setup cancelled.")
                try:
                    num_text = int(tmsg.content)
                except:
                    await ctx.send(
                        "❌ Invalid number; skipping text channels for this category."
                    )
                    num_text = 0
                for ti in range(num_text):
                    await ctx.send(
                        f"📝 Name for text channel #{ti+1} in **{cat_name}** (no #):"
                    )
                    chmsg = await bot.wait_for("message", check=check, timeout=120)
                    if is_cancel_or_stop(chmsg.content):
                        del setup_sessions[gid]
                        save_sessions()
                        return await ctx.send("❌ Setup cancelled.")
                    cat_entry["text_channels"].append(chmsg.content.strip())

                # voice channels
                await ctx.send(
                    f"🔊 How many voice channels under **{cat_name}**? (0 to skip)"
                )
                vmsg = await bot.wait_for("message", check=check, timeout=120)
                if is_cancel_or_stop(vmsg.content):
                    del setup_sessions[gid]
                    save_sessions()
                    return await ctx.send("❌ Setup cancelled.")
                try:
                    num_vc = int(vmsg.content)
                except:
                    await ctx.send(
                        "❌ Invalid number; skipping voice channels for this category."
                    )
                    num_vc = 0
                for vi in range(num_vc):
                    await ctx.send(
                        f"📝 Name for voice channel #{vi+1} in **{cat_name}**:"
                    )
                    vcmsg = await bot.wait_for("message", check=check, timeout=120)
                    if is_cancel_or_stop(vcmsg.content):
                        del setup_sessions[gid]
                        save_sessions()
                        return await ctx.send("❌ Setup cancelled.")
                    cat_entry["voice_channels"].append(vcmsg.content.strip())

                # permissions for this category - interactive
                # Ask if admin wants to set custom overwrites
                await ctx.send(
                    f"🔐 Do you want to set **custom permissions** for category **{cat_name}**? (yes/no)"
                )
                perm_choice = await bot.wait_for("message", check=check, timeout=120)
                if is_cancel_or_stop(perm_choice.content):
                    del setup_sessions[gid]
                    save_sessions()
                    return await ctx.send("❌ Setup cancelled.")
                if perm_choice.content.strip().lower() in ("yes", "y"):
                    await ctx.send(
                        "📋 Enter role names (comma-separated) that should **HAVE** access (view & send) to this category.\nExample: `Member, Moderator` or `@everyone` to allow everyone."
                    )
                    allow_msg = await bot.wait_for("message", check=check, timeout=180)
                    if is_cancel_or_stop(allow_msg.content):
                        del setup_sessions[gid]
                        save_sessions()
                        return await ctx.send("❌ Setup cancelled.")
                    allow_roles = [
                        r.strip() for r in allow_msg.content.split(",") if r.strip()
                    ]
                    # record permissions as allow list — we'll convert to overwrites at creation time
                    cat_entry["permissions"]["allow"] = allow_roles
                    # Optionally we can ask for denied roles
                    await ctx.send(
                        "📋 (Optional) Enter role names (comma-separated) to explicitly DENY view/send (leave blank to skip):"
                    )
                    deny_msg = await bot.wait_for("message", check=check, timeout=120)
                    if is_cancel_or_stop(deny_msg.content):
                        del setup_sessions[gid]
                        save_sessions()
                        return await ctx.send("❌ Setup cancelled.")
                    deny_roles = [
                        r.strip() for r in deny_msg.content.split(",") if r.strip()
                    ]
                    cat_entry["permissions"]["deny"] = deny_roles
                else:
                    cat_entry["permissions"] = {}  # inherit defaults

                session["categories"].append(cat_entry)
                setup_sessions[gid] = session
                save_sessions()

        else:
            await ctx.send(
                "📂 Categories already defined in the session; skipping category creation step."
            )

        # ---------- SUMMARY & CONFIRM ----------
        # build summary embed
        embed = discord.Embed(
            title="🧾 Server Setup Summary", color=discord.Color.green()
        )
        embed.add_field(
            name="Roles (to create)",
            value="\n".join(session["roles"]) or "None",
            inline=False,
        )
        if session["categories"]:
            for c in session["categories"]:
                name = c["name"]
                tlist = c.get("text_channels", [])
                vlist = c.get("voice_channels", [])
                perms = c.get("permissions", {})
                perm_str = ""
                if perms:
                    allow = ", ".join(perms.get("allow", [])) or "None"
                    deny = ", ".join(perms.get("deny", [])) or "None"
                    perm_str = f"Allow: {allow}\nDeny: {deny}"
                else:
                    perm_str = "Default"
                embed.add_field(
                    name=f"Category: {name}",
                    value=f"Text: {', '.join(tlist) or 'None'}\nVoice: {', '.join(vlist) or 'None'}\nPerms:\n{perm_str}",
                    inline=False,
                )
        else:
            embed.add_field(name="Categories", value="None", inline=False)

        embed.set_footer(
            text="Type `confirm` to create everything, `cancel` to abort. You can also use modular commands (see !setup)."
        )

        await ctx.send(embed=embed)
        confirm_msg = await bot.wait_for("message", check=check, timeout=180)
        if is_cancel_or_stop(confirm_msg.content):
            del setup_sessions[gid]
            save_sessions()
            return await ctx.send("❌ Setup cancelled.")
        if confirm_msg.content.strip().lower() not in ("confirm", "yes", "y"):
            return await ctx.send(
                "❌ Setup aborted by user. Run `!setupserver` again to restart."
            )

        # ---------- CREATION PHASE ----------
        await ctx.send(
            "⚙️ Creating roles, categories and channels now. I will post progress in the log channel."
        )
        # create roles (again, in case something changed)
        created_roles_map = {r.name: r for r in guild.roles}
        for rname in session["roles"]:
            if rname not in created_roles_map:
                try:
                    r = await guild.create_role(name=rname)
                    created_roles_map[r.name] = r
                    if log_channel:
                        await log_channel.send(f"➕ Created role `{r.name}`")
                except discord.Forbidden:
                    await ctx.send(
                        f"⚠️ Could not create role `{rname}` (missing Manage Roles). Continuing with other creations."
                    )
        # create categories and their channels with overwrites
        for c in session["categories"]:
            cname = c["name"]
            # prepare overwrites
            overwrites = {}
            # default: everyone no special deny - we'll later set allow for those in allow list
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=False
            )  # default lock, then we allow specific roles per config
            allow_list = c.get("permissions", {}).get("allow", [])
            deny_list = c.get("permissions", {}).get("deny", [])
            # allow selected roles
            for rn in allow_list:
                # ensure role exists
                role_obj = discord.utils.find(lambda rr: rr.name == rn, guild.roles)
                if not role_obj:
                    try:
                        role_obj = await guild.create_role(name=rn)
                        if log_channel:
                            await log_channel.send(
                                f"🆕 Created role `{rn}` for permission setup."
                            )
                    except discord.Forbidden:
                        role_obj = None
                if role_obj:
                    overwrites[role_obj] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True
                    )
            # explicit denies
            for rn in deny_list:
                role_obj = discord.utils.find(lambda rr: rr.name == rn, guild.roles)
                if role_obj:
                    overwrites[role_obj] = discord.PermissionOverwrite(
                        view_channel=False, send_messages=False
                    )

            try:
                cat = await guild.create_category(cname, overwrites=overwrites)
                if log_channel:
                    await log_channel.send(f"📁 Created category `{cname}`")
            except discord.Forbidden:
                await ctx.send(
                    f"⚠️ Missing permission to create category `{cname}`. Skipping."
                )
                continue

            # create text channels under this category
            for tc in c.get("text_channels", []):
                try:
                    ch = await guild.create_text_channel(tc, category=cat)
                    if log_channel:
                        await log_channel.send(
                            f"💬 Created text channel `{tc}` in `{cname}`"
                        )
                except discord.Forbidden:
                    if log_channel:
                        await log_channel.send(
                            f"⚠️ Could not create text channel `{tc}` (missing permission)."
                        )

            # create voice channels
            for vc in c.get("voice_channels", []):
                try:
                    vch = await guild.create_voice_channel(vc, category=cat)
                    if log_channel:
                        await log_channel.send(
                            f"🔊 Created voice channel `{vc}` in `{cname}`"
                        )
                except discord.Forbidden:
                    if log_channel:
                        await log_channel.send(
                            f"⚠️ Could not create voice channel `{vc}` (missing permission)."
                        )

        # final: mark session finished and save summary to log channel
        session["finished"] = True
        setup_sessions[gid] = session
        save_sessions()

        if log_channel:
            await log_channel.send("✅ Server setup completed successfully.")
            await log_channel.send(embed=embed)

        await ctx.send(
            "✅ Server setup complete! Check the admin/mod log channel for details."
        )
    except asyncio.TimeoutError:
        await ctx.send(
            "⌛ Setup timed out. Your progress is saved and you can resume with `!setupserver`."
        )
    except Exception as e:
        await ctx.send(f"⚠️ An unexpected error occurred: {e}")
        # keep session so admin can resume
        setup_sessions[gid] = session
        save_sessions()


# ---------- Modular subcommands ----------
@setup_group.command(name="addrole")
@commands.has_permissions(administrator=True)
async def setup_addrole(ctx, *, role_name: str):
    """Add a role manually to the server immediately (and save to session if active)."""
    guild = ctx.guild
    try:
        role = await guild.create_role(name=role_name)
        await ctx.send(f"✅ Role `{role.name}` created.")
        # add to session if one exists
        gid = str(guild.id)
        if gid in setup_sessions and not setup_sessions[gid].get("finished", False):
            setup_sessions[gid]["roles"].append(role.name)
            save_sessions()
            await ctx.send("ℹ️ Role added to the active setup session.")
    except discord.Forbidden:
        await ctx.send("⚠️ Missing Manage Roles permission.")


@setup_group.command(name="addcategory")
@commands.has_permissions(administrator=True)
async def setup_addcategory(ctx, *, category_name: str):
    """Add a category immediately (no channels)."""
    guild = ctx.guild
    try:
        cat = await guild.create_category(category_name)
        await ctx.send(f"✅ Category `{category_name}` created.")
        # append to session if active
        gid = str(guild.id)
        if gid in setup_sessions and not setup_sessions[gid].get("finished", False):
            setup_sessions[gid]["categories"].append(
                {
                    "name": category_name,
                    "text_channels": [],
                    "voice_channels": [],
                    "permissions": {},
                }
            )
            save_sessions()
            await ctx.send("ℹ️ Category added to the active setup session.")
    except discord.Forbidden:
        await ctx.send("⚠️ Missing Manage Channels permission.")


@setup_group.command(name="addchannel")
@commands.has_permissions(administrator=True)
async def setup_addchannel(
    ctx, category_name: str, channel_type: str, *, channel_name: str
):
    """
    Add a channel to a category immediately.
    Usage: !setup addchannel <category_name> <text|voice> <channel_name>
    """
    guild = ctx.guild
    cat = discord.utils.find(lambda c: c.name == category_name, guild.categories)
    if not cat:
        return await ctx.send("⚠️ Category not found.")
    try:
        if channel_type.lower() == "text":
            ch = await guild.create_text_channel(channel_name, category=cat)
            await ctx.send(
                f"✅ Text channel `{channel_name}` created in `{category_name}`."
            )
        elif channel_type.lower() in ("voice", "vc"):
            ch = await guild.create_voice_channel(channel_name, category=cat)
            await ctx.send(
                f"✅ Voice channel `{channel_name}` created in `{category_name}`."
            )
        else:
            return await ctx.send("⚠️ channel_type must be `text` or `voice`.")
        # add to session if active
        gid = str(guild.id)
        if gid in setup_sessions and not setup_sessions[gid].get("finished", False):
            for c in setup_sessions[gid]["categories"]:
                if c["name"] == category_name:
                    if channel_type.lower() == "text":
                        c["text_channels"].append(channel_name)
                    else:
                        c["voice_channels"].append(channel_name)
            save_sessions()
    except discord.Forbidden:
        await ctx.send("⚠️ Missing Manage Channels permission.")


@setup_group.command(name="permissions")
@commands.has_permissions(administrator=True)
async def setup_permissions(ctx, category_name: str):
    """
    Edit permissions stored in the active session for a category.
    The command is interactive: it will ask which roles to allow/deny.
    """
    gid = str(ctx.guild.id)
    if gid not in setup_sessions or setup_sessions[gid].get("finished", False):
        return await ctx.send("⚠️ No active setup session for this server.")
    session = setup_sessions[gid]
    target = None
    for c in session["categories"]:
        if c["name"] == category_name:
            target = c
            break
    if not target:
        return await ctx.send("⚠️ Category not found in session.")

    await ctx.send(
        "📋 Enter role names (comma-separated) to ALLOW (view & send) for this category:"
    )
    try:
        msg = await bot.wait_for(
            "message",
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
            timeout=120,
        )
        if is_cancel_or_stop(msg.content):
            return await ctx.send("❌ Permissions edit cancelled.")
        allow = [r.strip() for r in msg.content.split(",") if r.strip()]
        await ctx.send(
            "📋 Enter role names (comma-separated) to DENY (optional, blank to skip):"
        )
        msg2 = await bot.wait_for(
            "message",
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
            timeout=120,
        )
        if is_cancel_or_stop(msg2.content):
            return await ctx.send("❌ Permissions edit cancelled.")
        deny = [r.strip() for r in msg2.content.split(",") if r.strip()]
        target["permissions"] = {"allow": allow, "deny": deny}
        save_sessions()
        await ctx.send(
            "✅ Permissions saved to the session. They will be applied on confirm/create."
        )
    except asyncio.TimeoutError:
        await ctx.send("⌛ Timed out. Try `!setup permissions <category_name>` again.")


@setup_group.command(name="summary")
@commands.has_permissions(administrator=True)
async def setup_summary(ctx):
    """Show the summary of the active session for this guild."""
    gid = str(ctx.guild.id)
    if gid not in setup_sessions:
        return await ctx.send("ℹ️ No active setup session.")
    session = setup_sessions[gid]
    embed = discord.Embed(title="🧾 Active Setup Summary", color=discord.Color.orange())
    embed.add_field(
        name="Roles", value="\n".join(session.get("roles", [])) or "None", inline=False
    )
    if session.get("categories"):
        for c in session["categories"]:
            perms = c.get("permissions", {})
            allow = ", ".join(perms.get("allow", [])) if perms else "Default"
            deny = ", ".join(perms.get("deny", [])) if perms else "Default"
            embed.add_field(
                name=f"Category: {c['name']}",
                value=f"Text: {', '.join(c.get('text_channels',[])) or 'None'}\nVoice: {', '.join(c.get('voice_channels',[])) or 'None'}\nAllow: {allow}\nDeny: {deny}",
                inline=False,
            )
    await ctx.send(embed=embed)


@setup_group.command(name="confirm")
@commands.has_permissions(administrator=True)
async def setup_confirm(ctx):
    """Confirm and create using the active session (alias for final confirmation if user aborted earlier)."""
    gid = str(ctx.guild.id)
    if gid not in setup_sessions:
        return await ctx.send("⚠️ No active setup session.")
    session = setup_sessions[gid]
    # reuse the run_wizard creation phase by marking as if resuming and user typed confirm
    # Quick and safe approach: call run_wizard but ensure it goes straight to creation summary
    await ctx.send("⚙️ Starting creation from the saved session...")
    await run_wizard(ctx, session, resume=True)


@setup_group.command(name="cancel")
@commands.has_permissions(administrator=True)
async def setup_cancel(ctx):
    """Cancel and delete an active session."""
    gid = str(ctx.guild.id)
    if gid in setup_sessions:
        del setup_sessions[gid]
        save_sessions()
        await ctx.send("🗑️ Active setup session deleted.")
    else:
        await ctx.send("ℹ️ No active session to delete.")


@setup_group.command(name="template")
@commands.has_permissions(administrator=True)
async def setup_template(ctx, action: str = None, *, name: str = None):
    """
    Manage templates.
    Use: !setup template save <name>  (saves the current active session as a template)
         !setup template use <name>   (loads the template into an active session)
         !setup template list         (lists saved templates)
         !setup template delete <name>
    """
    gid = str(ctx.guild.id)
    if action is None:
        return await ctx.send("Usage: `!setup template save|use|list|delete <name>`")
    action = action.lower()
    if action == "list":
        if not templates:
            return await ctx.send("No templates saved.")
        await ctx.send("📚 Templates:\n" + "\n".join(templates.keys()))
    elif action == "save":
        if not name:
            return await ctx.send("Provide a name: `!setup template save <name>`")
        if gid not in setup_sessions:
            return await ctx.send("No active session to save as template.")
        templates[name] = setup_sessions[gid]
        save_templates()
        await ctx.send(f"✅ Template `{name}` saved.")
    elif action == "use":
        if not name:
            return await ctx.send("Provide a name to use.")
        if name not in templates:
            return await ctx.send("Template not found.")
        setup_sessions[gid] = templates[name]
        save_sessions()
        await ctx.send(
            f"✅ Template `{name}` loaded into active session. Use `!setup summary` to review and `!setup confirm` to create."
        )
    elif action == "delete":
        if not name:
            return await ctx.send("Provide a name to delete.")
        if name in templates:
            del templates[name]
            save_templates()
            await ctx.send(f"🗑️ Template `{name}` deleted.")
        else:
            await ctx.send("Template not found.")
    else:
        await ctx.send("Unknown action. Use save/use/list/delete.")


# ---------- End of setup system ----------


# ---------------- ERROR HANDLING ----------------
@add_role.error
@add_text_channel.error
@add_voice_channel.error
async def dynamic_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You do not have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Please provide a name for the role/channel.")
    else:
        await ctx.send(f"❌ Error: {str(error)}")


# ==================== MODERATION COMMANDS ENDS====================
# ==================== MODERATION COMMANDS ENDS====================
# ==================== MODERATION COMMANDS ENDS====================
# ==================== MODERATION COMMANDS ENDS====================
# =================== MODERATION COMMANDS ENDS====================
# ==================== MODERATION COMMANDS ENDS====================
# ==================== MODERATION COMMANDS ENDS====================


# Global error handler
@bot.event
async def on_command_error(ctx, error):
    """Global error handler for incorrect commands and common issues."""

    # Handle unknown command errors
    if isinstance(error, commands.CommandNotFound):
        # Extract the command user tried
        invalid_command = ctx.message.content.split()[0].replace(ctx.prefix, "")

        # Get list of all available commands
        all_commands = [cmd.name for cmd in bot.commands]

        # Find the closest match (if any)
        closest = get_close_matches(invalid_command, all_commands, n=1, cutoff=0.5)
        suggestion = closest[0] if closest else None

        # Build a clean and friendly embed
        embed = discord.Embed(title="❌ Command Not Found", color=discord.Color.red())

        embed.add_field(
            name="You tried:", value=f"`{ctx.prefix}{invalid_command}`", inline=False
        )

        if suggestion:
            embed.add_field(
                name="Did you mean:", value=f"`{ctx.prefix}{suggestion}`", inline=False
            )

            # If command exists, show a short help tip
            command_obj = bot.get_command(suggestion)
            if command_obj and command_obj.help:
                embed.add_field(
                    name="Command Info:", value=f"_{command_obj.help}_", inline=False
                )

        embed.add_field(
            name="Need help?",
            value=f"Type `{ctx.prefix}help` for a list of commands.",
            inline=False,
        )

        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )

        await ctx.send(embed=embed)
        return  # stop further error processing

    # Handle missing permissions
    elif isinstance(error, commands.MissingPermissions):
        missing = ", ".join(error.missing_permissions)
        await ctx.send(
            f"⚠️ You don’t have permission to use this command. Missing: `{missing}`"
        )

    # Handle missing required arguments
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"⚠️ Missing argument: `{error.param.name}`.\nType `{ctx.prefix}help {ctx.command}` for usage info."
        )

    # Handle any other error gracefully
    else:
        print(f"[ERROR] {type(error).__name__}: {error}")
        await ctx.send(
            "❗ An unexpected error occurred. The bot owner has been notified."
        )


# ------------------ Run Bot ------------------


if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: No token found in .env file!")

    else:
        bot.run(TOKEN)