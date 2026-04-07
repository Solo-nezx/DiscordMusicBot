import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import discord
from discord.ext import commands, tasks
from discord import app_commands
import yt_dlp
import asyncio
import os
import time
import random
from collections import deque
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
INACTIVITY_TIMEOUT = 15 * 60          # 15 minutes in seconds
EMBED_COLOR        = 0x1DB954          # Spotify green
EMBED_COLOR_WARN   = 0xFF6B6B          # Red for warnings
EMBED_COLOR_QUEUE  = 0x5865F2          # Discord blurple for queue

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "cookiefile": None,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# ─────────────────────────────────────────────
#  Per-guild player state
# ─────────────────────────────────────────────
players: dict = {}   # guild_id -> dict

def get_player(guild: discord.Guild) -> dict:
    if guild.id not in players:
        players[guild.id] = {
            "queue":        deque(),
            "history":      deque(maxlen=20),
            "current":      None,
            "voice_client": None,
            "text_channel": None,
            "loop":         False,
            "shuffle":      False,
            "volume":       0.5,
            "paused":       False,
            "np_message":   None,
            "last_activity":time.time(),
            "idle_task":    None,
        }
    return players[guild.id]

# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def format_duration(seconds: int) -> str:
    if not seconds:
        return "مجهول"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

async def fetch_song(query: str) -> dict | None:
    """Fetch song info from YouTube (blocking → run in executor)."""
    loop = asyncio.get_event_loop()
    def _fetch():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return {
                "title":       info.get("title", "Unknown"),
                "url":         info["url"],
                "webpage_url": info.get("webpage_url", ""),
                "thumbnail":   info.get("thumbnail", ""),
                "duration":    info.get("duration", 0),
                "uploader":    info.get("uploader", "Unknown"),
                "requester":   None,   # filled later
            }
    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        print(f"[yt-dlp] Error: {e}")
        return None

def build_now_playing_embed(song: dict, player: dict) -> discord.Embed:
    loop_icon    = "🔁 مفعّل" if player["loop"]    else "⬛ معطّل"
    shuffle_icon = "🔀 مفعّل" if player["shuffle"] else "⬛ معطّل"
    queue_len    = len(player["queue"])
    requester    = song.get("requester")

    embed = discord.Embed(
        title="🎵  يُشغَّل الآن",
        description=f"### [{song['title']}]({song['webpage_url']})",
        color=EMBED_COLOR,
    )
    if song.get("thumbnail"):
        embed.set_image(url=song["thumbnail"])

    embed.add_field(name="⏱️ المدة",          value=format_duration(song.get("duration", 0)), inline=True)
    embed.add_field(name="🎤 الفنان",          value=song.get("uploader", "Unknown"),           inline=True)
    embed.add_field(name="🔊 الصوت",           value=f"{int(player['volume'] * 100)}%",         inline=True)
    embed.add_field(name="🔁 التكرار",         value=loop_icon,                                  inline=True)
    embed.add_field(name="🔀 العشوائي",        value=shuffle_icon,                               inline=True)
    embed.add_field(name="📋 في الطابور",      value=str(queue_len),                             inline=True)

    if requester:
        embed.set_footer(
            text=f"طُلبت بواسطة {requester.display_name}",
            icon_url=requester.display_avatar.url,
        )
    else:
        embed.set_footer(text="🎧 Music Bot")
    return embed

def build_queue_embed(player: dict) -> discord.Embed:
    embed = discord.Embed(title="📋  قائمة الانتظار", color=EMBED_COLOR_QUEUE)
    current = player.get("current")
    if current:
        embed.add_field(
            name="▶️  يُشغَّل الآن",
            value=f"[{current['title']}]({current['webpage_url']}) — `{format_duration(current.get('duration',0))}`",
            inline=False,
        )
    q = list(player["queue"])
    if q:
        lines = []
        for i, s in enumerate(q[:10], 1):
            lines.append(f"`{i}.` [{s['title']}]({s['webpage_url']}) — `{format_duration(s.get('duration',0))}`")
        if len(q) > 10:
            lines.append(f"… و {len(q) - 10} أغنية أخرى")
        embed.add_field(name="⏭️  التالي", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="⏭️  التالي", value="القائمة فارغة", inline=False)
    return embed

# ─────────────────────────────────────────────
#  Music Controls View (buttons)
# ─────────────────────────────────────────────
class MusicView(discord.ui.View):
    """Persistent view attached to the Now-Playing message."""

    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot      = bot
        self.guild_id = guild_id

    def _player(self):
        return players.get(self.guild_id)

    # ── Row 0 ──────────────────────────────────
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="mb_prev",  row=0)
    async def btn_prev(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        if not p["history"]:
            return await interaction.response.send_message("❌ لا يوجد سجل سابق.", ephemeral=True)

        if p["current"]:
            p["queue"].appendleft(p["current"])
        prev = p["history"].pop()
        p["queue"].appendleft(prev)

        vc = p["voice_client"]
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

        p["last_activity"] = time.time()
        await interaction.response.defer()

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, custom_id="mb_pause", row=0)
    async def btn_pause(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        vc = p["voice_client"]
        if not vc:
            return await interaction.response.send_message("❌ البوت ليس في روم صوتي.", ephemeral=True)

        if vc.is_playing():
            vc.pause()
            p["paused"] = True
            btn.emoji   = discord.PartialEmoji.from_str("▶️")
            btn.style   = discord.ButtonStyle.success
        elif vc.is_paused():
            vc.resume()
            p["paused"] = False
            btn.emoji   = discord.PartialEmoji.from_str("⏸️")
            btn.style   = discord.ButtonStyle.primary
        else:
            return await interaction.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)

        p["last_activity"] = time.time()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger,     custom_id="mb_stop",  row=0)
    async def btn_stop(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        p["queue"].clear()
        p["current"] = None
        vc = p["voice_client"]
        if vc and vc.is_connected():
            vc.stop()
        p["last_activity"] = time.time()
        await interaction.response.send_message("⏹️ تم الإيقاف ومسح القائمة.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="mb_skip",  row=0)
    async def btn_skip(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        vc = p["voice_client"]
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            p["last_activity"] = time.time()
            await interaction.response.send_message("⏭️ تم التخطي!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)

    # ── Row 1 ──────────────────────────────────
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="mb_loop",    row=1)
    async def btn_loop(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        p["loop"] = not p["loop"]
        btn.style = discord.ButtonStyle.success if p["loop"] else discord.ButtonStyle.secondary
        msg = "🔁 التكرار مفعَّل!" if p["loop"] else "🔁 التكرار معطَّل!"
        p["last_activity"] = time.time()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

        # Refresh Now Playing embed
        if p["current"] and p["np_message"]:
            try:
                await p["np_message"].edit(embed=build_now_playing_embed(p["current"], p))
            except Exception:
                pass

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="mb_shuffle", row=1)
    async def btn_shuffle(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        p["shuffle"] = not p["shuffle"]
        btn.style = discord.ButtonStyle.success if p["shuffle"] else discord.ButtonStyle.secondary
        msg = "🔀 الخلط العشوائي مفعَّل!" if p["shuffle"] else "🔀 الخلط العشوائي معطَّل!"
        p["last_activity"] = time.time()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

        if p["current"] and p["np_message"]:
            try:
                await p["np_message"].edit(embed=build_now_playing_embed(p["current"], p))
            except Exception:
                pass

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="mb_voldn",   row=1)
    async def btn_vol_down(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        p["volume"] = max(0.0, round(p["volume"] - 0.1, 1))
        vc = p["voice_client"]
        if vc and vc.source:
            vc.source.volume = p["volume"]
        p["last_activity"] = time.time()
        await interaction.response.send_message(f"🔉 الصوت: **{int(p['volume']*100)}%**", ephemeral=True)

        if p["current"] and p["np_message"]:
            try:
                await p["np_message"].edit(embed=build_now_playing_embed(p["current"], p))
            except Exception:
                pass

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="mb_volup",   row=1)
    async def btn_vol_up(self, interaction: discord.Interaction, btn: discord.ui.Button):
        p = self._player()
        if not p:
            return await interaction.response.send_message("❌ لا توجد موسيقى.", ephemeral=True)
        p["volume"] = min(1.0, round(p["volume"] + 0.1, 1))
        vc = p["voice_client"]
        if vc and vc.source:
            vc.source.volume = p["volume"]
        p["last_activity"] = time.time()
        await interaction.response.send_message(f"🔊 الصوت: **{int(p['volume']*100)}%**", ephemeral=True)

        if p["current"] and p["np_message"]:
            try:
                await p["np_message"].edit(embed=build_now_playing_embed(p["current"], p))
            except Exception:
                pass

# ─────────────────────────────────────────────
#  Core playback logic
# ─────────────────────────────────────────────
async def play_next(guild: discord.Guild):
    """Advance to the next song (or start inactivity timer)."""
    p = get_player(guild)

    # Decide what to play next
    if p["loop"] and p["current"]:
        next_song = p["current"]
    elif p["queue"]:
        if p["shuffle"]:
            q_list = list(p["queue"])
            random.shuffle(q_list)
            p["queue"] = deque(q_list)
        next_song = p["queue"].popleft()
    else:
        # Queue exhausted → show idle embed and start inactivity timer
        p["current"] = None
        if p["np_message"]:
            try:
                idle_embed = discord.Embed(
                    title="✅  انتهت القائمة",
                    description="لا توجد أغاني أخرى.\n⏳ سيغادر البوت بعد **15 دقيقة** من عدم الاستخدام.",
                    color=EMBED_COLOR_WARN,
                )
                await p["np_message"].edit(embed=idle_embed, view=None)
            except Exception:
                pass
        p["last_activity"] = time.time()
        _start_idle_task(guild, p)
        return

    # Save current to history before replacing
    if p["current"] and not (p["loop"] and p["current"] is next_song):
        p["history"].append(p["current"])

    p["current"] = next_song
    p["last_activity"] = time.time()

    # Build FFmpeg source
    source = discord.FFmpegPCMAudio(next_song["url"], **FFMPEG_OPTS)
    source = discord.PCMVolumeTransformer(source, volume=p["volume"])

    def _after(error):
        if error:
            print(f"[Player] Playback error: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"[Player] after-callback error: {e}")

    p["voice_client"].play(source, after=_after)
    p["paused"] = False

    # Build / update Now-Playing message
    embed = build_now_playing_embed(next_song, p)
    view  = MusicView(bot, guild.id)

    channel = p["text_channel"]
    if channel:
        if p["np_message"]:
            try:
                await p["np_message"].edit(embed=embed, view=view)
                return
            except Exception:
                pass
        try:
            p["np_message"] = await channel.send(embed=embed, view=view)
        except Exception as e:
            print(f"[Player] Could not send NP message: {e}")

def _start_idle_task(guild: discord.Guild, p: dict):
    if p["idle_task"] and not p["idle_task"].done():
        p["idle_task"].cancel()
    p["idle_task"] = asyncio.create_task(_idle_watcher(guild))

async def _idle_watcher(guild: discord.Guild):
    """Disconnect after INACTIVITY_TIMEOUT seconds of no playback."""
    await asyncio.sleep(INACTIVITY_TIMEOUT)
    p = players.get(guild.id)
    if not p:
        return
    vc = p["voice_client"]
    if vc and vc.is_connected() and not vc.is_playing() and not vc.is_paused():
        elapsed = time.time() - p["last_activity"]
        if elapsed >= INACTIVITY_TIMEOUT:
            await vc.disconnect()
            channel = p.get("text_channel")
            if channel:
                try:
                    bye = discord.Embed(
                        title="👋  مغادرة تلقائية",
                        description="غادر البوت بسبب عدم الاستخدام لمدة **15 دقيقة**.",
                        color=EMBED_COLOR_WARN,
                    )
                    await channel.send(embed=bye)
                except Exception:
                    pass
            players.pop(guild.id, None)

# ─────────────────────────────────────────────
#  Bot setup
# ─────────────────────────────────────────────
intents                 = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅  Bot connected as: {bot.user}  (ID: {bot.user.id})")
    print("─" * 40)
    try:
        synced = await bot.tree.sync()
        print(f"✅  Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌  Sync error: {e}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="/play 🎵",
        )
    )

# ─────────────────────────────────────────────
#  Slash Commands
# ─────────────────────────────────────────────

@bot.tree.command(name="play", description="🎵 شغّل أغنية من YouTube (اسم أو رابط)")
@app_commands.describe(query="اسم الأغنية أو رابط YouTube")
async def cmd_play(interaction: discord.Interaction, query: str):
    # Must be in a voice channel
    if not interaction.user.voice:
        return await interaction.response.send_message(
            embed=discord.Embed(description="❌ يجب أن تكون في روم صوتي أولاً!", color=EMBED_COLOR_WARN),
            ephemeral=True,
        )

    await interaction.response.defer(thinking=True)

    p  = get_player(interaction.guild)
    vc = p["voice_client"]

    # Connect / move
    if vc is None or not vc.is_connected():
        try:
            vc = await interaction.user.voice.channel.connect()
            p["voice_client"] = vc
        except Exception as e:
            return await interaction.followup.send(f"❌ تعذّر الاتصال: {e}", ephemeral=True)
    elif vc.channel != interaction.user.voice.channel:
        await vc.move_to(interaction.user.voice.channel)

    p["text_channel"] = interaction.channel

    # Cancel any idle timer
    if p["idle_task"] and not p["idle_task"].done():
        p["idle_task"].cancel()

    # Fetch song info
    song = await fetch_song(query)
    if not song:
        return await interaction.followup.send(
            embed=discord.Embed(description="❌ لم أجد الأغنية. جرب رابطاً آخر أو اسماً مختلفاً.", color=EMBED_COLOR_WARN),
            ephemeral=True,
        )
    song["requester"] = interaction.user

    if vc.is_playing() or vc.is_paused():
        p["queue"].append(song)
        queued_embed = discord.Embed(
            title="📋  أُضيفت إلى الطابور",
            description=f"[{song['title']}]({song['webpage_url']})",
            color=EMBED_COLOR_QUEUE,
        )
        queued_embed.add_field(name="⏱️ المدة",    value=format_duration(song.get("duration", 0)), inline=True)
        queued_embed.add_field(name="📋 الموضع", value=str(len(p["queue"])),                       inline=True)
        if song.get("thumbnail"):
            queued_embed.set_thumbnail(url=song["thumbnail"])
        await interaction.followup.send(embed=queued_embed)
    else:
        p["queue"].appendleft(song)
        await interaction.followup.send(
            embed=discord.Embed(description=f"▶️ جاري تشغيل **{song['title']}**…", color=EMBED_COLOR),
        )
        await play_next(interaction.guild)


@bot.tree.command(name="pause", description="⏸️ إيقاف مؤقت للأغنية الحالية")
async def cmd_pause(interaction: discord.Interaction):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    if vc and vc.is_playing():
        vc.pause()
        p["paused"] = True
        await interaction.response.send_message("⏸️ تم الإيقاف المؤقت.")
    else:
        await interaction.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)


@bot.tree.command(name="resume", description="▶️ استئناف التشغيل")
async def cmd_resume(interaction: discord.Interaction):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    if vc and vc.is_paused():
        vc.resume()
        p["paused"] = False
        await interaction.response.send_message("▶️ تم استئناف التشغيل.")
    else:
        await interaction.response.send_message("❌ لا شيء موقوف مؤقتاً.", ephemeral=True)


@bot.tree.command(name="skip", description="⏭️ تخطي الأغنية الحالية")
async def cmd_skip(interaction: discord.Interaction):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message("⏭️ تم التخطي!")
    else:
        await interaction.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)


@bot.tree.command(name="stop", description="⏹️ إيقاف التشغيل ومسح الطابور")
async def cmd_stop(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["queue"].clear()
    p["current"] = None
    vc = p["voice_client"]
    if vc and vc.is_connected():
        vc.stop()
    await interaction.response.send_message("⏹️ تم إيقاف التشغيل ومسح الطابور.")


@bot.tree.command(name="queue", description="📋 عرض قائمة الانتظار")
async def cmd_queue(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    await interaction.response.send_message(embed=build_queue_embed(p))


@bot.tree.command(name="nowplaying", description="🎵 عرض الأغنية التي تُشغَّل الآن")
async def cmd_nowplaying(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    if not p["current"]:
        return await interaction.response.send_message("❌ لا شيء يُشغَّل الآن.", ephemeral=True)
    embed = build_now_playing_embed(p["current"], p)
    view  = MusicView(bot, interaction.guild.id)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="volume", description="🔊 ضبط مستوى الصوت (0 - 100)")
@app_commands.describe(level="مستوى الصوت من 0 إلى 100")
async def cmd_volume(interaction: discord.Interaction, level: int):
    if not 0 <= level <= 100:
        return await interaction.response.send_message("❌ القيمة يجب أن تكون بين 0 و 100.", ephemeral=True)
    p = get_player(interaction.guild)
    p["volume"] = level / 100
    vc = p["voice_client"]
    if vc and vc.source:
        vc.source.volume = p["volume"]
    await interaction.response.send_message(f"🔊 تم ضبط الصوت على **{level}%**.")


@bot.tree.command(name="loop", description="🔁 تفعيل/إيقاف تكرار الأغنية الحالية")
async def cmd_loop(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["loop"] = not p["loop"]
    status = "مفعَّل ✅" if p["loop"] else "معطَّل ❌"
    await interaction.response.send_message(f"🔁 التكرار الآن: **{status}**")


@bot.tree.command(name="shuffle", description="🔀 تفعيل/إيقاف الخلط العشوائي")
async def cmd_shuffle(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["shuffle"] = not p["shuffle"]
    status = "مفعَّل ✅" if p["shuffle"] else "معطَّل ❌"
    await interaction.response.send_message(f"🔀 الخلط العشوائي الآن: **{status}**")


@bot.tree.command(name="remove", description="🗑️ حذف أغنية من الطابور")
@app_commands.describe(position="رقم الأغنية في الطابور")
async def cmd_remove(interaction: discord.Interaction, position: int):
    p = get_player(interaction.guild)
    q = list(p["queue"])
    if not 1 <= position <= len(q):
        return await interaction.response.send_message("❌ رقم غير صالح.", ephemeral=True)
    removed = q.pop(position - 1)
    p["queue"] = deque(q)
    await interaction.response.send_message(f"🗑️ تم حذف **{removed['title']}** من الطابور.")


@bot.tree.command(name="clear", description="🗑️ مسح كل الطابور")
async def cmd_clear(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["queue"].clear()
    await interaction.response.send_message("🗑️ تم مسح الطابور بالكامل.")


@bot.tree.command(name="disconnect", description="👋 إخراج البوت من الروم الصوتي")
async def cmd_disconnect(interaction: discord.Interaction):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    if vc and vc.is_connected():
        p["queue"].clear()
        p["current"] = None
        await vc.disconnect()
        players.pop(interaction.guild.id, None)
        await interaction.response.send_message("👋 تم قطع الاتصال.")
    else:
        await interaction.response.send_message("❌ البوت ليس في أي روم صوتي.", ephemeral=True)


@bot.tree.command(name="help", description="📖 عرض جميع الأوامر")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖  قائمة الأوامر",
        description="جميع الأوامر المتاحة في بوت الموسيقى",
        color=EMBED_COLOR,
    )
    commands_list = [
        ("/play [اسم أو رابط]",  "🎵 تشغيل أغنية من YouTube"),
        ("/pause",               "⏸️ إيقاف مؤقت"),
        ("/resume",              "▶️ استئناف التشغيل"),
        ("/skip",                "⏭️ تخطي الأغنية الحالية"),
        ("/stop",                "⏹️ إيقاف ومسح الطابور"),
        ("/queue",               "📋 عرض قائمة الانتظار"),
        ("/nowplaying",          "🎵 الأغنية الحالية مع الأزرار"),
        ("/volume [0-100]",      "🔊 ضبط مستوى الصوت"),
        ("/loop",                "🔁 تكرار الأغنية الحالية"),
        ("/shuffle",             "🔀 خلط عشوائي"),
        ("/remove [رقم]",        "🗑️ حذف أغنية من الطابور"),
        ("/clear",               "🗑️ مسح كل الطابور"),
        ("/disconnect",          "👋 إخراج البوت من الروم"),
    ]
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)

    embed.add_field(
        name="🎮  الأزرار",
        value="⏮️ السابق | ⏸️/▶️ إيقاف/تشغيل | ⏹️ إيقاف | ⏭️ تخطي | 🔁 تكرار | 🔀 عشوائي | 🔉🔊 صوت",
        inline=False,
    )
    embed.set_footer(text="⏳ البوت يغادر تلقائياً بعد 15 دقيقة من عدم الاستخدام")
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        print("❌  DISCORD_TOKEN غير موجود في ملف .env")
    else:
        print("🚀  بدء تشغيل البوت…")
        bot.run(TOKEN)
