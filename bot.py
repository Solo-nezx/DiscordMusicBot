import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import time
import random
import json
import math
import re
import aiohttp
from collections import deque
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
INACTIVITY_TIMEOUT   = 15 * 60
PROGRESS_BAR_LENGTH  = 18
PLAYLISTS_FILE       = "playlists.json"

COLOR_GREEN  = 0x1DB954   # Spotify green  — now playing
COLOR_WARN   = 0xFF6B6B   # Red            — warnings
COLOR_QUEUE  = 0x5865F2   # Blurple        — queue
COLOR_FILTER = 0xF0A500   # Gold           — filters
COLOR_LYRICS = 0x9B59B6   # Purple         — lyrics
COLOR_HIST   = 0x2ECC71   # Emerald        — history

# ─────────────────────────────────────────────
#  Audio Filters
# ─────────────────────────────────────────────
AUDIO_FILTERS: dict[str, str] = {
    "bassboost":  "bass=g=20,dynaudnorm=f=200",
    "nightcore":  "asetrate=44100*1.25,aresample=44100",
    "vaporwave":  "asetrate=44100*0.8,aresample=44100",
    "8d":         "apulsator=hz=0.125",
    "slowreverb": "asetrate=44100*0.85,aresample=44100,aecho=0.8:0.88:60:0.4",
    "karaoke":    "pan=stereo|c0=c0-c1|c1=c1-c0",
    "earrape":    "acrusher=level_in=8:level_out=18:bits=8:mode=log:aa=1",
    "mono":       "pan=mono|c0=0.5*c0+0.5*c1",
}

FILTER_LABELS: dict[str, str] = {
    "bassboost":  "باص بوست 🔊",
    "nightcore":  "نايت كور ⚡",
    "vaporwave":  "فيبور ويف 🌊",
    "8d":         "ثلاثي الأبعاد 🎧",
    "slowreverb": "سلو + ريفيرب 🌙",
    "karaoke":    "كاريوكي 🎤",
    "earrape":    "إير ريب 💥",
    "mono":       "مونو 🔉",
}

# ─────────────────────────────────────────────
#  yt-dlp options
# ─────────────────────────────────────────────
_YDL_BASE = {
    "format":             "bestaudio/best",
    "nocheckcertificate": True,
    "ignoreerrors":       False,
    "quiet":              True,
    "no_warnings":        True,
    "default_search":     "ytsearch",
    "source_address":     "0.0.0.0",
}
YDL_OPTS          = {**_YDL_BASE, "noplaylist": True}
YDL_PLAYLIST_OPTS = {**_YDL_BASE, "noplaylist": False, "playlistend": 50}


def _ffmpeg_opts(seek: int = 0, audio_filter: str | None = None) -> dict:
    before  = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    if seek > 0:
        before = f"-ss {seek} " + before
    options = f"-vn -af \"{audio_filter}\"" if audio_filter else "-vn"
    return {"before_options": before, "options": options}


# ─────────────────────────────────────────────
#  Saved playlists (JSON)
# ─────────────────────────────────────────────
def _load_playlists() -> dict:
    if os.path.exists(PLAYLISTS_FILE):
        try:
            with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_playlists(data: dict) -> None:
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
#  Per-guild player state
# ─────────────────────────────────────────────
players: dict = {}


def get_player(guild: discord.Guild) -> dict:
    if guild.id not in players:
        players[guild.id] = {
            "queue":        deque(),
            "history":      deque(maxlen=30),
            "current":      None,
            "voice_client": None,
            "text_channel": None,
            "loop":         False,
            "loop_queue":   False,
            "shuffle":      False,
            "autoplay":     False,
            "mode_247":     False,
            "volume":       0.5,
            "paused":       False,
            "filter":       None,
            "np_message":   None,
            "last_activity":time.time(),
            "idle_task":    None,
            "np_task":      None,
            "start_time":   None,
            "seek_offset":  0,
            "_restarting":  False,
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


def get_elapsed(p: dict) -> int:
    if p["start_time"] is None:
        return 0
    return int(time.time() - p["start_time"]) + p["seek_offset"]


def progress_bar(current: int, total: int, length: int = PROGRESS_BAR_LENGTH) -> str:
    if not total:
        return "░" * length
    filled = min(int((current / total) * length), length)
    return "█" * filled + "░" * (length - filled)


def _extract_info(info: dict) -> dict:
    return {
        "title":       info.get("title", "Unknown"),
        "url":         info.get("url", ""),
        "webpage_url": info.get("webpage_url", ""),
        "thumbnail":   info.get("thumbnail", ""),
        "duration":    info.get("duration", 0),
        "uploader":    info.get("uploader", "Unknown"),
        "requester":   None,
    }


async def fetch_song(query: str) -> dict | None:
    loop = asyncio.get_running_loop()
    def _fetch():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return _extract_info(info)
    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        print(f"[yt-dlp] {e}")
        return None


async def fetch_playlist(url: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    def _fetch():
        with yt_dlp.YoutubeDL(YDL_PLAYLIST_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            if "entries" not in info:
                return [_extract_info(info)]
            return [_extract_info(e) for e in info["entries"] if e]
    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        print(f"[yt-dlp playlist] {e}")
        return []


async def fetch_search(query: str, count: int = 5) -> list[dict]:
    loop = asyncio.get_running_loop()
    def _fetch():
        opts = {**YDL_OPTS, "default_search": f"ytsearch{count}"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
            return [_extract_info(e) for e in (info.get("entries") or []) if e]
    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        print(f"[yt-dlp search] {e}")
        return []


async def fetch_lyrics(title: str, artist: str = "") -> str | None:
    clean_title  = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
    clean_artist = artist.strip()
    if not clean_artist or clean_artist.lower() in ("unknown", "vevo", ""):
        if " - " in clean_title:
            parts        = clean_title.split(" - ", 1)
            clean_artist = parts[0].strip()
            clean_title  = parts[1].strip()
        else:
            clean_artist = "unknown"
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.lyrics.ovh/v1/{clean_artist}/{clean_title}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("lyrics")
    except Exception as e:
        print(f"[lyrics] {e}")
    return None


# ─────────────────────────────────────────────
#  Embed builders
# ─────────────────────────────────────────────
def build_np_embed(song: dict, p: dict) -> discord.Embed:
    elapsed   = get_elapsed(p)
    total     = song.get("duration", 0)
    bar       = progress_bar(elapsed, total)
    progress  = f"`{format_duration(elapsed)}` {bar} `{format_duration(total)}`"

    icon = lambda flag: "🟢" if flag else "⬛"
    filter_txt = FILTER_LABELS.get(p["filter"], "لا يوجد") if p["filter"] else "لا يوجد"

    embed = discord.Embed(
        title="🎵  يُشغَّل الآن",
        description=f"### [{song['title']}]({song['webpage_url']})\n\n{progress}",
        color=COLOR_GREEN,
    )
    if song.get("thumbnail"):
        embed.set_image(url=song["thumbnail"])

    embed.add_field(name="🎤 الفنان",        value=song.get("uploader", "Unknown"),  inline=True)
    embed.add_field(name="🔊 الصوت",         value=f"{int(p['volume'] * 100)}%",     inline=True)
    embed.add_field(name="🎛️ فلتر",          value=filter_txt,                       inline=True)
    embed.add_field(name="🔁 تكرار أغنية",   value=icon(p["loop"]),                  inline=True)
    embed.add_field(name="🔂 تكرار قائمة",   value=icon(p["loop_queue"]),            inline=True)
    embed.add_field(name="🔀 عشوائي",        value=icon(p["shuffle"]),               inline=True)
    embed.add_field(name="🤖 تلقائي",        value=icon(p["autoplay"]),              inline=True)
    embed.add_field(name="🔒 24/7",          value=icon(p["mode_247"]),              inline=True)
    embed.add_field(name="📋 الطابور",       value=str(len(p["queue"])),             inline=True)

    requester = song.get("requester")
    if requester:
        embed.set_footer(
            text=f"طُلبت بواسطة {requester.display_name}",
            icon_url=requester.display_avatar.url,
        )
    else:
        embed.set_footer(text="🎧 Music Bot Pro")
    return embed


def build_queue_embed(p: dict, page: int = 0) -> tuple[discord.Embed, int]:
    q        = list(p["queue"])
    per_page = 10
    total_pg = max(1, math.ceil(len(q) / per_page))
    page     = max(0, min(page, total_pg - 1))
    start    = page * per_page

    embed = discord.Embed(
        title=f"📋  قائمة الانتظار  —  صفحة {page + 1}/{total_pg}",
        color=COLOR_QUEUE,
    )

    current = p.get("current")
    if current:
        elapsed = get_elapsed(p)
        total   = current.get("duration", 0)
        bar     = progress_bar(elapsed, total, length=12)
        embed.add_field(
            name="▶️  يُشغَّل الآن",
            value=(
                f"[{current['title']}]({current['webpage_url']})\n"
                f"`{format_duration(elapsed)}` {bar} `{format_duration(total)}`"
            ),
            inline=False,
        )

    if q:
        lines = [
            f"`{i + 1}.` [{s['title']}]({s['webpage_url']}) — `{format_duration(s.get('duration', 0))}`"
            for i, s in enumerate(q[start: start + per_page], start)
        ]
        embed.add_field(name="⏭️  التالي", value="\n".join(lines), inline=False)
        total_dur = sum(s.get("duration", 0) for s in q)
        status = []
        if p["loop"]:       status.append("🔁 تكرار أغنية")
        if p["loop_queue"]: status.append("🔂 تكرار قائمة")
        if p["shuffle"]:    status.append("🔀 عشوائي")
        embed.set_footer(
            text=f"{'  |  '.join(status) + '  •  ' if status else ''}"
                 f"{len(q)} أغنية  •  مدة إجمالية: {format_duration(total_dur)}"
        )
    else:
        embed.add_field(name="⏭️  التالي", value="القائمة فارغة", inline=False)

    return embed, total_pg


# ─────────────────────────────────────────────
#  Music Controls View  (3 rows of buttons)
# ─────────────────────────────────────────────
class MusicView(discord.ui.View):
    def __init__(self, bot_ref: commands.Bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot_ref  = bot_ref
        self.guild_id = guild_id

    def _p(self) -> dict | None:
        return players.get(self.guild_id)

    # ── Row 0  ─────────────────────────────────────────────────────────────
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="mb_prev",  row=0)
    async def btn_prev(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        if not p["history"]:
            return await ix.response.send_message("❌ لا يوجد سجل سابق.", ephemeral=True)
        if p["current"]:
            p["queue"].appendleft(p["current"])
        p["queue"].appendleft(p["history"].pop())
        vc = p["voice_client"]
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        p["last_activity"] = time.time()
        await ix.response.defer()

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, custom_id="mb_pause", row=0)
    async def btn_pause(self, ix: discord.Interaction, btn: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        vc = p["voice_client"]
        if not vc: return await ix.response.send_message("❌ البوت ليس في روم صوتي.", ephemeral=True)
        if vc.is_playing():
            vc.pause(); p["paused"] = True
            btn.emoji = discord.PartialEmoji.from_str("▶️")
            btn.style = discord.ButtonStyle.success
        elif vc.is_paused():
            vc.resume(); p["paused"] = False
            btn.emoji = discord.PartialEmoji.from_str("⏸️")
            btn.style = discord.ButtonStyle.primary
        else:
            return await ix.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)
        p["last_activity"] = time.time()
        await ix.response.edit_message(view=self)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger,    custom_id="mb_stop",  row=0)
    async def btn_stop(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["queue"].clear(); p["current"] = None
        vc = p["voice_client"]
        if vc and vc.is_connected(): vc.stop()
        p["last_activity"] = time.time()
        await ix.response.send_message("⏹️ تم الإيقاف ومسح القائمة.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="mb_skip",  row=0)
    async def btn_skip(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        vc = p["voice_client"]
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop(); p["last_activity"] = time.time()
            await ix.response.send_message("⏭️ تم التخطي!", ephemeral=True)
        else:
            await ix.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)

    # ── Row 1  ─────────────────────────────────────────────────────────────
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="mb_loop",  row=1)
    async def btn_loop(self, ix: discord.Interaction, btn: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["loop"] = not p["loop"]
        if p["loop"]: p["loop_queue"] = False
        btn.style = discord.ButtonStyle.success if p["loop"] else discord.ButtonStyle.secondary
        p["last_activity"] = time.time()
        await ix.response.edit_message(view=self)
        await ix.followup.send("🔁 تكرار الأغنية: " + ("مفعَّل ✅" if p["loop"] else "معطَّل ❌"), ephemeral=True)
        await _refresh_np(p)

    @discord.ui.button(emoji="🔂", style=discord.ButtonStyle.secondary, custom_id="mb_loopq", row=1)
    async def btn_loop_queue(self, ix: discord.Interaction, btn: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["loop_queue"] = not p["loop_queue"]
        if p["loop_queue"]: p["loop"] = False
        btn.style = discord.ButtonStyle.success if p["loop_queue"] else discord.ButtonStyle.secondary
        p["last_activity"] = time.time()
        await ix.response.edit_message(view=self)
        await ix.followup.send("🔂 تكرار القائمة: " + ("مفعَّل ✅" if p["loop_queue"] else "معطَّل ❌"), ephemeral=True)
        await _refresh_np(p)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="mb_shuf",  row=1)
    async def btn_shuffle(self, ix: discord.Interaction, btn: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["shuffle"] = not p["shuffle"]
        btn.style = discord.ButtonStyle.success if p["shuffle"] else discord.ButtonStyle.secondary
        p["last_activity"] = time.time()
        await ix.response.edit_message(view=self)
        await ix.followup.send("🔀 الخلط العشوائي: " + ("مفعَّل ✅" if p["shuffle"] else "معطَّل ❌"), ephemeral=True)
        await _refresh_np(p)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="mb_voldn", row=1)
    async def btn_vol_dn(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["volume"] = max(0.0, round(p["volume"] - 0.1, 1))
        vc = p["voice_client"]
        if vc and vc.source: vc.source.volume = p["volume"]
        p["last_activity"] = time.time()
        await ix.response.send_message(f"🔉 الصوت: **{int(p['volume'] * 100)}%**", ephemeral=True)
        await _refresh_np(p)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="mb_volup", row=1)
    async def btn_vol_up(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["volume"] = min(2.0, round(p["volume"] + 0.1, 1))
        vc = p["voice_client"]
        if vc and vc.source: vc.source.volume = p["volume"]
        p["last_activity"] = time.time()
        await ix.response.send_message(f"🔊 الصوت: **{int(p['volume'] * 100)}%**", ephemeral=True)
        await _refresh_np(p)

    # ── Row 2  ─────────────────────────────────────────────────────────────
    @discord.ui.button(label="📋 طابور", style=discord.ButtonStyle.secondary, custom_id="mb_queue",  row=2)
    async def btn_queue(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        embed, _ = build_queue_embed(p)
        await ix.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🎤 كلمات", style=discord.ButtonStyle.secondary, custom_id="mb_lyric", row=2)
    async def btn_lyrics(self, ix: discord.Interaction, _: discord.ui.Button):
        p = self._p()
        if not p or not p["current"]:
            return await ix.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)
        await ix.response.defer(ephemeral=True)
        song   = p["current"]
        lyrics = await fetch_lyrics(song["title"], song.get("uploader", ""))
        if not lyrics:
            return await ix.followup.send("❌ لم أجد كلمات لهذه الأغنية.", ephemeral=True)
        if len(lyrics) > 3900: lyrics = lyrics[:3900] + "\n…"
        await ix.followup.send(
            embed=discord.Embed(title=f"🎤 {song['title']}", description=lyrics, color=COLOR_LYRICS),
            ephemeral=True,
        )

    @discord.ui.button(label="🤖 تلقائي", style=discord.ButtonStyle.secondary, custom_id="mb_auto",  row=2)
    async def btn_autoplay(self, ix: discord.Interaction, btn: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["autoplay"] = not p["autoplay"]
        btn.style = discord.ButtonStyle.success if p["autoplay"] else discord.ButtonStyle.secondary
        p["last_activity"] = time.time()
        await ix.response.edit_message(view=self)
        await ix.followup.send("🤖 التشغيل التلقائي: " + ("مفعَّل ✅" if p["autoplay"] else "معطَّل ❌"), ephemeral=True)
        await _refresh_np(p)

    @discord.ui.button(label="🔒 24/7", style=discord.ButtonStyle.secondary, custom_id="mb_247",    row=2)
    async def btn_247(self, ix: discord.Interaction, btn: discord.ui.Button):
        p = self._p()
        if not p: return await ix.response.send_message("❌", ephemeral=True)
        p["mode_247"] = not p["mode_247"]
        btn.style = discord.ButtonStyle.success if p["mode_247"] else discord.ButtonStyle.secondary
        p["last_activity"] = time.time()
        await ix.response.edit_message(view=self)
        await ix.followup.send("🔒 وضع 24/7: " + ("مفعَّل ✅" if p["mode_247"] else "معطَّل ❌"), ephemeral=True)
        await _refresh_np(p)


async def _refresh_np(p: dict) -> None:
    """Silently refresh the Now Playing embed."""
    if p.get("current") and p.get("np_message"):
        try:
            await p["np_message"].edit(embed=build_np_embed(p["current"], p))
        except Exception:
            pass


# ─────────────────────────────────────────────
#  Queue Paginator
# ─────────────────────────────────────────────
class QueueView(discord.ui.View):
    def __init__(self, p: dict):
        super().__init__(timeout=60)
        self.p    = p
        self.page = 0

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, ix: discord.Interaction, _: discord.ui.Button):
        self.page = max(0, self.page - 1)
        embed, _ = build_queue_embed(self.p, self.page)
        await ix.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, ix: discord.Interaction, _: discord.ui.Button):
        _, total = build_queue_embed(self.p, self.page)
        self.page = min(total - 1, self.page + 1)
        embed, _ = build_queue_embed(self.p, self.page)
        await ix.response.edit_message(embed=embed, view=self)


# ─────────────────────────────────────────────
#  Search Select
# ─────────────────────────────────────────────
class _SearchSelect(discord.ui.Select):
    def __init__(self, results: list[dict], guild: discord.Guild):
        self.results = results
        self.guild   = guild
        super().__init__(
            placeholder="اختر أغنية…",
            options=[
                discord.SelectOption(
                    label=r["title"][:100],
                    description=f"{r.get('uploader', 'Unknown')} — {format_duration(r.get('duration', 0))}",
                    value=str(i),
                )
                for i, r in enumerate(results)
            ],
        )

    async def callback(self, ix: discord.Interaction):
        song = self.results[int(self.values[0])]
        song["requester"] = ix.user

        if not ix.user.voice:
            return await ix.response.send_message("❌ يجب أن تكون في روم صوتي أولاً!", ephemeral=True)

        await ix.response.defer()

        p  = get_player(self.guild)
        vc = p["voice_client"]

        if vc is None or not vc.is_connected():
            try:
                vc = await ix.user.voice.channel.connect()
                p["voice_client"] = vc
            except Exception as e:
                return await ix.followup.send(f"❌ تعذّر الاتصال: {e}", ephemeral=True)
        elif vc.channel != ix.user.voice.channel:
            await vc.move_to(ix.user.voice.channel)

        p["text_channel"] = ix.channel
        _cancel_idle(p)

        if vc.is_playing() or vc.is_paused():
            p["queue"].append(song)
            embed = discord.Embed(
                title="📋  أُضيفت إلى الطابور",
                description=f"[{song['title']}]({song['webpage_url']})",
                color=COLOR_QUEUE,
            )
            embed.add_field(name="📋 الموضع", value=str(len(p["queue"])), inline=True)
            if song.get("thumbnail"):
                embed.set_thumbnail(url=song["thumbnail"])
            await ix.followup.send(embed=embed)
        else:
            p["queue"].appendleft(song)
            await ix.followup.send(
                embed=discord.Embed(description=f"▶️ جاري تشغيل **{song['title']}**…", color=COLOR_GREEN)
            )
            await play_next(self.guild)

        self.view.stop()


class SearchView(discord.ui.View):
    def __init__(self, results: list[dict], guild: discord.Guild):
        super().__init__(timeout=30)
        self.add_item(_SearchSelect(results, guild))


# ─────────────────────────────────────────────
#  Core playback
# ─────────────────────────────────────────────
def _cancel_idle(p: dict) -> None:
    if p["idle_task"] and not p["idle_task"].done():
        p["idle_task"].cancel()


async def play_next(guild: discord.Guild) -> None:
    p = get_player(guild)

    # ── Determine next song ──────────────────────────
    is_restarting = p.pop("_restarting", False)

    if is_restarting and p["current"]:
        next_song          = p["current"]
        add_to_history     = False
    elif p["loop"] and p["current"]:
        next_song          = p["current"]
        add_to_history     = False
        p["seek_offset"]   = 0
    elif p["queue"]:
        if p["shuffle"]:
            q = list(p["queue"])
            random.shuffle(q)
            p["queue"] = deque(q)
        if p["loop_queue"] and p["current"]:
            p["queue"].append(p["current"])   # rotate: re-add to end
        next_song        = p["queue"].popleft()
        add_to_history   = True
        p["seek_offset"] = 0
    elif p["autoplay"] and p["current"]:
        related = await _autoplay_song(p["current"])
        if related:
            next_song      = related
            add_to_history = True
            p["seek_offset"] = 0
        else:
            await _queue_empty(guild, p)
            return
    else:
        await _queue_empty(guild, p)
        return

    # ── History ──────────────────────────────────────
    if add_to_history and p["current"] and p["current"] is not next_song:
        p["history"].append(p["current"])

    p["current"]       = next_song
    p["last_activity"] = time.time()
    p["start_time"]    = time.time()

    # ── Build audio source ───────────────────────────
    fopts  = _ffmpeg_opts(seek=p["seek_offset"], audio_filter=AUDIO_FILTERS.get(p["filter"]))
    source = discord.FFmpegPCMAudio(next_song["url"], **fopts)
    source = discord.PCMVolumeTransformer(source, volume=p["volume"])

    def _after(error):
        if error:
            print(f"[Player] Playback error: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"[Player] _after error: {e}")

    p["voice_client"].play(source, after=_after)
    p["paused"] = False

    # ── Now Playing message ──────────────────────────
    embed   = build_np_embed(next_song, p)
    view    = MusicView(bot, guild.id)
    channel = p["text_channel"]

    if channel:
        if p["np_message"]:
            try:
                await p["np_message"].edit(embed=embed, view=view)
                _start_np_updater(guild, p)
                return
            except Exception:
                pass
        try:
            p["np_message"] = await channel.send(embed=embed, view=view)
            _start_np_updater(guild, p)
        except Exception as e:
            print(f"[Player] NP send error: {e}")


async def _queue_empty(guild: discord.Guild, p: dict) -> None:
    p["current"]    = None
    p["start_time"] = None
    if p["np_message"]:
        try:
            await p["np_message"].edit(
                embed=discord.Embed(
                    title="✅  انتهت القائمة",
                    description="لا توجد أغاني أخرى.\n⏳ سيغادر البوت بعد **15 دقيقة** من عدم الاستخدام.",
                    color=COLOR_WARN,
                ),
                view=None,
            )
        except Exception:
            pass
    p["last_activity"] = time.time()
    if not p["mode_247"]:
        _start_idle(guild, p)


async def _autoplay_song(current: dict) -> dict | None:
    clean = re.sub(r"\(.*?\)|\[.*?\]|official|video|lyrics|hd|hq", "", current["title"], flags=re.IGNORECASE).strip()
    results = await fetch_search(f"{clean} related", count=6)
    for r in results:
        if r["webpage_url"] != current.get("webpage_url"):
            return r
    return None


def _start_idle(guild: discord.Guild, p: dict) -> None:
    _cancel_idle(p)
    p["idle_task"] = asyncio.create_task(_idle_watcher(guild))


async def _idle_watcher(guild: discord.Guild) -> None:
    await asyncio.sleep(INACTIVITY_TIMEOUT)
    p = players.get(guild.id)
    if not p: return
    vc = p["voice_client"]
    if vc and vc.is_connected() and not vc.is_playing() and not vc.is_paused():
        if time.time() - p["last_activity"] >= INACTIVITY_TIMEOUT:
            await vc.disconnect()
            channel = p.get("text_channel")
            if channel:
                try:
                    await channel.send(embed=discord.Embed(
                        title="👋  مغادرة تلقائية",
                        description="غادر البوت بسبب عدم الاستخدام لمدة **15 دقيقة**.",
                        color=COLOR_WARN,
                    ))
                except Exception:
                    pass
            players.pop(guild.id, None)


def _start_np_updater(guild: discord.Guild, p: dict) -> None:
    if p.get("np_task") and not p["np_task"].done():
        p["np_task"].cancel()
    p["np_task"] = asyncio.create_task(_np_updater(guild))


async def _np_updater(guild: discord.Guild) -> None:
    """Refresh the progress bar every 20 seconds."""
    while True:
        await asyncio.sleep(20)
        p  = players.get(guild.id)
        if not p or not p["current"] or not p["np_message"]: break
        vc = p.get("voice_client")
        if not vc or not (vc.is_playing() or vc.is_paused()): break
        try:
            await p["np_message"].edit(embed=build_np_embed(p["current"], p))
        except Exception:
            break


async def _restart_playback(p: dict, seek: int | None = None) -> None:
    """Re-fetch URL then restart current song with seek / filter."""
    fresh = await fetch_song(p["current"]["webpage_url"])
    if fresh:
        p["current"]["url"] = fresh["url"]

    elapsed             = get_elapsed(p) if seek is None else seek
    p["seek_offset"]    = elapsed
    p["start_time"]     = time.time()
    p["_restarting"]    = True

    vc = p["voice_client"]
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()   # triggers _after → play_next → sees _restarting


# ─────────────────────────────────────────────
#  Bot setup
# ─────────────────────────────────────────────
intents                 = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅  Bot ready: {bot.user}  (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅  Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌  Sync error: {e}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="/play 🎵")
    )


# ─────────────────────────────────────────────
#  Slash Commands
# ─────────────────────────────────────────────

async def _ensure_voice(interaction: discord.Interaction, p: dict) -> discord.VoiceClient | None:
    """Connect / move bot to user's voice channel. Returns vc or None on failure."""
    vc = p["voice_client"]
    if vc is None or not vc.is_connected():
        try:
            vc = await interaction.user.voice.channel.connect()
            p["voice_client"] = vc
        except Exception as e:
            await interaction.followup.send(f"❌ تعذّر الاتصال: {e}", ephemeral=True)
            return None
    elif vc.channel != interaction.user.voice.channel:
        await vc.move_to(interaction.user.voice.channel)
    return vc


# ── /play ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="play", description="🎵 شغّل أغنية أو قائمة تشغيل من YouTube (اسم أو رابط)")
@app_commands.describe(query="اسم الأغنية، رابط YouTube، أو رابط قائمة تشغيل")
async def cmd_play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        return await interaction.response.send_message(
            embed=discord.Embed(description="❌ يجب أن تكون في روم صوتي أولاً!", color=COLOR_WARN),
            ephemeral=True,
        )
    await interaction.response.defer(thinking=True)

    p  = get_player(interaction.guild)
    vc = await _ensure_voice(interaction, p)
    if not vc: return

    p["text_channel"] = interaction.channel
    _cancel_idle(p)

    # ── Playlist detection ────────────────────────────
    is_playlist = "playlist" in query.lower() or "list=" in query
    if is_playlist:
        songs = await fetch_playlist(query)
        if not songs:
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ لم أتمكن من تحميل القائمة.", color=COLOR_WARN), ephemeral=True
            )
        for s in songs:
            s["requester"] = interaction.user

        playing_now = not (vc.is_playing() or vc.is_paused())
        for s in songs:
            p["queue"].append(s)

        embed = discord.Embed(color=COLOR_GREEN if playing_now else COLOR_QUEUE)
        embed.title       = "🎵 تشغيل قائمة تشغيل" if playing_now else "📋 أُضيفت قائمة التشغيل"
        embed.description = f"تمت إضافة **{len(songs)}** أغنية إلى الطابور."
        await interaction.followup.send(embed=embed)

        if playing_now:
            await play_next(interaction.guild)
        return

    # ── Single song ───────────────────────────────────
    song = await fetch_song(query)
    if not song:
        return await interaction.followup.send(
            embed=discord.Embed(description="❌ لم أجد الأغنية. جرب رابطاً آخر أو اسماً مختلفاً.", color=COLOR_WARN),
            ephemeral=True,
        )
    song["requester"] = interaction.user

    if vc.is_playing() or vc.is_paused():
        p["queue"].append(song)
        embed = discord.Embed(
            title="📋  أُضيفت إلى الطابور",
            description=f"[{song['title']}]({song['webpage_url']})",
            color=COLOR_QUEUE,
        )
        embed.add_field(name="⏱️ المدة",  value=format_duration(song.get("duration", 0)), inline=True)
        embed.add_field(name="📋 الموضع", value=str(len(p["queue"])),                     inline=True)
        if song.get("thumbnail"): embed.set_thumbnail(url=song["thumbnail"])
        await interaction.followup.send(embed=embed)
    else:
        p["queue"].appendleft(song)
        await interaction.followup.send(
            embed=discord.Embed(description=f"▶️ جاري تشغيل **{song['title']}**…", color=COLOR_GREEN)
        )
        await play_next(interaction.guild)


# ── /search ────────────────────────────────────────────────────────────────
@bot.tree.command(name="search", description="🔍 ابحث عن أغنية واختر من النتائج")
@app_commands.describe(query="كلمات البحث")
async def cmd_search(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        return await interaction.response.send_message(
            embed=discord.Embed(description="❌ يجب أن تكون في روم صوتي أولاً!", color=COLOR_WARN), ephemeral=True
        )
    await interaction.response.defer(thinking=True)
    results = await fetch_search(query, count=5)
    if not results:
        return await interaction.followup.send(
            embed=discord.Embed(description="❌ لم أجد نتائج.", color=COLOR_WARN), ephemeral=True
        )
    lines = "\n".join(
        f"`{i+1}.` [{r['title']}]({r['webpage_url']}) — `{format_duration(r.get('duration', 0))}`"
        for i, r in enumerate(results)
    )
    embed = discord.Embed(title=f"🔍  نتائج البحث: {query}", description=lines, color=COLOR_QUEUE)
    await interaction.followup.send(embed=embed, view=SearchView(results, interaction.guild))


# ── /seek ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="seek", description="⏩ الانتقال إلى وقت محدد في الأغنية الحالية")
@app_commands.describe(seconds="الوقت بالثواني (مثال: 90 للانتقال إلى الثانية 90)")
async def cmd_seek(interaction: discord.Interaction, seconds: int):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    if not p["current"] or not vc or not (vc.is_playing() or vc.is_paused()):
        return await interaction.response.send_message("❌ لا شيء يُشغَّل الآن.", ephemeral=True)
    duration = p["current"].get("duration", 0)
    if duration and not 0 <= seconds <= duration:
        return await interaction.response.send_message(
            f"❌ الوقت يجب أن يكون بين 0 و {format_duration(duration)}.", ephemeral=True
        )
    await interaction.response.defer(thinking=True)
    await _restart_playback(p, seek=seconds)
    await interaction.followup.send(
        embed=discord.Embed(description=f"⏩ تم الانتقال إلى **{format_duration(seconds)}**", color=COLOR_GREEN)
    )


# ── /filter ────────────────────────────────────────────────────────────────
@bot.tree.command(name="filter", description="🎛️ تطبيق فلتر صوتي على الأغنية الحالية")
@app_commands.describe(name="اسم الفلتر المطلوب")
@app_commands.choices(name=[
    app_commands.Choice(name="باص بوست 🔊",      value="bassboost"),
    app_commands.Choice(name="نايت كور ⚡",       value="nightcore"),
    app_commands.Choice(name="فيبور ويف 🌊",      value="vaporwave"),
    app_commands.Choice(name="ثلاثي الأبعاد 🎧",  value="8d"),
    app_commands.Choice(name="سلو + ريفيرب 🌙",  value="slowreverb"),
    app_commands.Choice(name="كاريوكي 🎤",        value="karaoke"),
    app_commands.Choice(name="إير ريب 💥",        value="earrape"),
    app_commands.Choice(name="مونو 🔉",           value="mono"),
    app_commands.Choice(name="بدون فلتر ❌",      value="none"),
])
async def cmd_filter(interaction: discord.Interaction, name: str):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    if not p["current"] or not vc or not (vc.is_playing() or vc.is_paused()):
        return await interaction.response.send_message("❌ لا شيء يُشغَّل الآن.", ephemeral=True)
    await interaction.response.defer(thinking=True)

    p["filter"] = None if name == "none" else name
    await _restart_playback(p)

    label = FILTER_LABELS.get(p["filter"], "بدون فلتر ❌") if p["filter"] else "بدون فلتر ❌"
    await interaction.followup.send(
        embed=discord.Embed(description=f"🎛️ تم تطبيق الفلتر: **{label}**", color=COLOR_FILTER)
    )


# ── /lyrics ────────────────────────────────────────────────────────────────
@bot.tree.command(name="lyrics", description="🎤 عرض كلمات الأغنية الحالية أو أي أغنية")
@app_commands.describe(song_name="اسم الأغنية (اتركه فارغاً للأغنية الحالية)")
async def cmd_lyrics(interaction: discord.Interaction, song_name: str = ""):
    await interaction.response.defer(thinking=True)
    p = get_player(interaction.guild)

    if song_name:
        title, uploader = song_name, ""
    elif p["current"]:
        title, uploader = p["current"]["title"], p["current"].get("uploader", "")
    else:
        return await interaction.followup.send("❌ لا شيء يُشغَّل الآن. حدد اسم الأغنية.", ephemeral=True)

    lyrics = await fetch_lyrics(title, uploader)
    if not lyrics:
        return await interaction.followup.send(
            embed=discord.Embed(description="❌ لم أجد كلمات لهذه الأغنية.", color=COLOR_WARN)
        )
    if len(lyrics) > 3900: lyrics = lyrics[:3900] + "\n…"
    await interaction.followup.send(
        embed=discord.Embed(title=f"🎤 {title}", description=lyrics, color=COLOR_LYRICS)
    )


# ── /move ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="move", description="🔄 تحريك أغنية من موضع لآخر في الطابور")
@app_commands.describe(from_pos="الموضع الحالي", to_pos="الموضع الجديد")
async def cmd_move(interaction: discord.Interaction, from_pos: int, to_pos: int):
    p = get_player(interaction.guild)
    q = list(p["queue"])
    if not (1 <= from_pos <= len(q) and 1 <= to_pos <= len(q)):
        return await interaction.response.send_message("❌ مواضع غير صالحة.", ephemeral=True)
    song = q.pop(from_pos - 1)
    q.insert(to_pos - 1, song)
    p["queue"] = deque(q)
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"🔄 نُقلت **{song['title']}**\nمن الموضع `{from_pos}` ← إلى `{to_pos}`",
            color=COLOR_QUEUE,
        )
    )


# ── /jump ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="jump", description="⏩ القفز مباشرة إلى أغنية محددة في الطابور")
@app_commands.describe(position="رقم الأغنية في الطابور")
async def cmd_jump(interaction: discord.Interaction, position: int):
    p  = get_player(interaction.guild)
    vc = p["voice_client"]
    q  = list(p["queue"])
    if not 1 <= position <= len(q):
        return await interaction.response.send_message("❌ رقم غير صالح.", ephemeral=True)
    skipped         = q[:position - 1]
    p["queue"]      = deque(q[position - 1:])
    p["history"].extend(skipped)
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
    await interaction.response.send_message(
        embed=discord.Embed(description=f"⏩ تم القفز إلى الأغنية رقم `{position}`", color=COLOR_GREEN)
    )


# ── /history ───────────────────────────────────────────────────────────────
@bot.tree.command(name="history", description="📜 عرض سجل الأغاني التي شُغِّلت مؤخراً")
async def cmd_history(interaction: discord.Interaction):
    p    = get_player(interaction.guild)
    hist = list(p["history"])
    if not hist:
        return await interaction.response.send_message(
            embed=discord.Embed(description="📜 السجل فارغ.", color=COLOR_HIST), ephemeral=True
        )
    lines = [
        f"`{i}.` [{s['title']}]({s['webpage_url']}) — `{format_duration(s.get('duration', 0))}`"
        for i, s in enumerate(reversed(hist), 1)
    ]
    await interaction.response.send_message(
        embed=discord.Embed(title="📜  سجل التشغيل", description="\n".join(lines), color=COLOR_HIST),
        ephemeral=True,
    )


# ── /autoplay ──────────────────────────────────────────────────────────────
@bot.tree.command(name="autoplay", description="🤖 تفعيل/إيقاف التشغيل التلقائي عند انتهاء القائمة")
async def cmd_autoplay(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["autoplay"] = not p["autoplay"]
    status = "مفعَّل ✅" if p["autoplay"] else "معطَّل ❌"
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🤖 التشغيل التلقائي: **{status}**", color=COLOR_GREEN)
    )


# ── /247 ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="247", description="🔒 تفعيل/إيقاف وضع البقاء الدائم في الروم الصوتي")
async def cmd_247(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["mode_247"] = not p["mode_247"]
    status = "مفعَّل ✅" if p["mode_247"] else "معطَّل ❌"
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔒 وضع 24/7: **{status}**", color=COLOR_GREEN)
    )


# ── /save ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="save", description="💾 حفظ الطابور الحالي كقائمة تشغيل")
@app_commands.describe(name="اسم القائمة")
async def cmd_save(interaction: discord.Interaction, name: str):
    p = get_player(interaction.guild)
    q = ([p["current"]] if p["current"] else []) + list(p["queue"])
    if not q:
        return await interaction.response.send_message("❌ لا توجد أغاني للحفظ.", ephemeral=True)
    playlists = _load_playlists()
    key       = str(interaction.guild.id)
    if key not in playlists: playlists[key] = {}
    playlists[key][name] = [
        {"title": s["title"], "webpage_url": s["webpage_url"], "duration": s.get("duration", 0)}
        for s in q
    ]
    _save_playlists(playlists)
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"💾 تم حفظ **{len(q)}** أغنية في القائمة: **{name}**",
            color=COLOR_GREEN,
        )
    )


# ── /load ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="load", description="📂 تحميل قائمة تشغيل محفوظة وإضافتها للطابور")
@app_commands.describe(name="اسم القائمة")
async def cmd_load(interaction: discord.Interaction, name: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ يجب أن تكون في روم صوتي أولاً!", ephemeral=True)
    saved = _load_playlists().get(str(interaction.guild.id), {})
    if name not in saved:
        return await interaction.response.send_message(f"❌ القائمة **{name}** غير موجودة.", ephemeral=True)

    await interaction.response.defer(thinking=True)
    p  = get_player(interaction.guild)
    vc = await _ensure_voice(interaction, p)
    if not vc: return

    p["text_channel"] = interaction.channel
    _cancel_idle(p)

    for s in saved[name]:
        entry = {**s, "url": s["webpage_url"], "thumbnail": "", "uploader": "محفوظ", "requester": interaction.user}
        p["queue"].append(entry)

    await interaction.followup.send(
        embed=discord.Embed(
            description=f"📂 تم تحميل **{len(saved[name])}** أغنية من: **{name}**",
            color=COLOR_GREEN,
        )
    )
    if not vc.is_playing() and not vc.is_paused():
        await play_next(interaction.guild)


# ── /playlists ─────────────────────────────────────────────────────────────
@bot.tree.command(name="playlists", description="📂 عرض قوائم التشغيل المحفوظة في هذا السيرفر")
async def cmd_playlists(interaction: discord.Interaction):
    saved = _load_playlists().get(str(interaction.guild.id), {})
    if not saved:
        return await interaction.response.send_message(
            embed=discord.Embed(description="📂 لا توجد قوائم تشغيل محفوظة.", color=COLOR_QUEUE), ephemeral=True
        )
    lines = [f"**{name}** — {len(songs)} أغنية" for name, songs in saved.items()]
    await interaction.response.send_message(
        embed=discord.Embed(title="📂  قوائم التشغيل", description="\n".join(lines), color=COLOR_QUEUE),
        ephemeral=True,
    )


# ── Standard commands ──────────────────────────────────────────────────────
@bot.tree.command(name="pause", description="⏸️ إيقاف مؤقت للأغنية الحالية")
async def cmd_pause(interaction: discord.Interaction):
    p = get_player(interaction.guild); vc = p["voice_client"]
    if vc and vc.is_playing():
        vc.pause(); p["paused"] = True
        await interaction.response.send_message(
            embed=discord.Embed(description="⏸️ تم الإيقاف المؤقت.", color=COLOR_GREEN)
        )
    else:
        await interaction.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)


@bot.tree.command(name="resume", description="▶️ استئناف تشغيل الأغنية")
async def cmd_resume(interaction: discord.Interaction):
    p = get_player(interaction.guild); vc = p["voice_client"]
    if vc and vc.is_paused():
        vc.resume(); p["paused"] = False
        await interaction.response.send_message(
            embed=discord.Embed(description="▶️ تم استئناف التشغيل.", color=COLOR_GREEN)
        )
    else:
        await interaction.response.send_message("❌ لا شيء موقوف مؤقتاً.", ephemeral=True)


@bot.tree.command(name="skip", description="⏭️ تخطي الأغنية الحالية")
async def cmd_skip(interaction: discord.Interaction):
    p = get_player(interaction.guild); vc = p["voice_client"]
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message(
            embed=discord.Embed(description="⏭️ تم التخطي!", color=COLOR_GREEN)
        )
    else:
        await interaction.response.send_message("❌ لا شيء يُشغَّل.", ephemeral=True)


@bot.tree.command(name="stop", description="⏹️ إيقاف التشغيل ومسح الطابور بالكامل")
async def cmd_stop(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["queue"].clear(); p["current"] = None
    vc = p["voice_client"]
    if vc and vc.is_connected(): vc.stop()
    await interaction.response.send_message(
        embed=discord.Embed(description="⏹️ تم إيقاف التشغيل ومسح الطابور.", color=COLOR_WARN)
    )


@bot.tree.command(name="queue", description="📋 عرض قائمة الانتظار (مع دعم تقليب الصفحات)")
async def cmd_queue(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    embed, total = build_queue_embed(p)
    if total > 1:
        await interaction.response.send_message(embed=embed, view=QueueView(p))
    else:
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="nowplaying", description="🎵 عرض الأغنية الحالية مع لوحة تحكم كاملة")
async def cmd_nowplaying(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    if not p["current"]:
        return await interaction.response.send_message("❌ لا شيء يُشغَّل الآن.", ephemeral=True)
    await interaction.response.send_message(
        embed=build_np_embed(p["current"], p),
        view=MusicView(bot, interaction.guild.id),
    )


@bot.tree.command(name="volume", description="🔊 ضبط مستوى الصوت (0 – 200)")
@app_commands.describe(level="مستوى الصوت من 0 إلى 200  (100 = عادي، 200 = مضاعف)")
async def cmd_volume(interaction: discord.Interaction, level: int):
    if not 0 <= level <= 200:
        return await interaction.response.send_message("❌ القيمة يجب أن تكون بين 0 و 200.", ephemeral=True)
    p = get_player(interaction.guild); p["volume"] = level / 100
    vc = p["voice_client"]
    if vc and vc.source: vc.source.volume = p["volume"]
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔊 تم ضبط الصوت على **{level}%**", color=COLOR_GREEN)
    )


@bot.tree.command(name="loop", description="🔁 تفعيل/إيقاف تكرار الأغنية الحالية")
async def cmd_loop(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["loop"] = not p["loop"]
    if p["loop"]: p["loop_queue"] = False
    status = "مفعَّل ✅" if p["loop"] else "معطَّل ❌"
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔁 تكرار الأغنية: **{status}**", color=COLOR_GREEN)
    )


@bot.tree.command(name="loopqueue", description="🔂 تفعيل/إيقاف تكرار القائمة بأكملها")
async def cmd_loopqueue(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["loop_queue"] = not p["loop_queue"]
    if p["loop_queue"]: p["loop"] = False
    status = "مفعَّل ✅" if p["loop_queue"] else "معطَّل ❌"
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔂 تكرار القائمة: **{status}**", color=COLOR_GREEN)
    )


@bot.tree.command(name="shuffle", description="🔀 تفعيل/إيقاف الخلط العشوائي")
async def cmd_shuffle(interaction: discord.Interaction):
    p = get_player(interaction.guild)
    p["shuffle"] = not p["shuffle"]
    status = "مفعَّل ✅" if p["shuffle"] else "معطَّل ❌"
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔀 الخلط العشوائي: **{status}**", color=COLOR_GREEN)
    )


@bot.tree.command(name="remove", description="🗑️ حذف أغنية محددة من الطابور")
@app_commands.describe(position="رقم الأغنية في الطابور")
async def cmd_remove(interaction: discord.Interaction, position: int):
    p = get_player(interaction.guild); q = list(p["queue"])
    if not 1 <= position <= len(q):
        return await interaction.response.send_message("❌ رقم غير صالح.", ephemeral=True)
    removed = q.pop(position - 1); p["queue"] = deque(q)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🗑️ تم حذف **{removed['title']}** من الطابور.", color=COLOR_WARN)
    )


@bot.tree.command(name="clear", description="🗑️ مسح جميع الأغاني من الطابور")
async def cmd_clear(interaction: discord.Interaction):
    p = get_player(interaction.guild); p["queue"].clear()
    await interaction.response.send_message(
        embed=discord.Embed(description="🗑️ تم مسح الطابور بالكامل.", color=COLOR_WARN)
    )


@bot.tree.command(name="disconnect", description="👋 إخراج البوت من الروم الصوتي")
async def cmd_disconnect(interaction: discord.Interaction):
    p = get_player(interaction.guild); vc = p["voice_client"]
    if vc and vc.is_connected():
        p["queue"].clear(); p["current"] = None
        await vc.disconnect()
        players.pop(interaction.guild.id, None)
        await interaction.response.send_message(
            embed=discord.Embed(description="👋 تم قطع الاتصال.", color=COLOR_WARN)
        )
    else:
        await interaction.response.send_message("❌ البوت ليس في أي روم صوتي.", ephemeral=True)


@bot.tree.command(name="help", description="📖 عرض جميع الأوامر المتاحة")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖  دليل الأوامر الكامل",
        description="بوت موسيقى متكامل مدعوم بـ YouTube مع فلاتر صوتية وكلمات أغاني",
        color=COLOR_GREEN,
    )
    sections = {
        "🎵 التشغيل": [
            ("/play [اسم/رابط]",   "تشغيل أغنية أو قائمة تشغيل YouTube"),
            ("/search [كلمات]",    "بحث واختيار من 5 نتائج"),
            ("/seek [ثواني]",      "الانتقال لوقت محدد في الأغنية"),
            ("/nowplaying",        "عرض الأغنية الحالية + لوحة تحكم"),
            ("/pause / /resume",   "إيقاف مؤقت / استئناف"),
            ("/skip",              "تخطي الأغنية الحالية"),
            ("/stop",              "إيقاف التشغيل ومسح الطابور"),
        ],
        "📋 إدارة الطابور": [
            ("/queue",             "عرض الطابور مع تقليب الصفحات"),
            ("/move [من] [إلى]",   "تحريك أغنية لموضع آخر"),
            ("/jump [رقم]",        "القفز مباشرة لأغنية محددة"),
            ("/remove [رقم]",      "حذف أغنية من الطابور"),
            ("/clear",             "مسح الطابور بالكامل"),
            ("/history",           "عرض آخر 30 أغنية مشغَّلة"),
        ],
        "⚙️ إعدادات التشغيل": [
            ("/volume [0-200]",    "ضبط مستوى الصوت (100 = عادي)"),
            ("/loop",              "🔁 تكرار الأغنية الحالية"),
            ("/loopqueue",         "🔂 تكرار القائمة بأكملها"),
            ("/shuffle",           "🔀 تشغيل عشوائي"),
            ("/autoplay",          "🤖 تشغيل تلقائي عند انتهاء القائمة"),
            ("/247",               "🔒 البقاء الدائم في الروم الصوتي"),
            ("/filter [نوع]",      "🎛️ تطبيق فلتر صوتي"),
        ],
        "💾 قوائم التشغيل": [
            ("/save [اسم]",        "حفظ الطابور الحالي"),
            ("/load [اسم]",        "تحميل قائمة محفوظة"),
            ("/playlists",         "عرض القوائم المحفوظة"),
        ],
        "🎤 أخرى": [
            ("/lyrics [اسم؟]",     "عرض كلمات الأغنية الحالية أو أي أغنية"),
            ("/disconnect",        "إخراج البوت من الروم"),
        ],
    }
    for section, cmds in sections.items():
        embed.add_field(
            name=section,
            value="\n".join(f"`{c}` — {d}" for c, d in cmds),
            inline=False,
        )
    embed.add_field(
        name="🎛️ الفلاتر الصوتية",
        value="باص بوست 🔊 | نايت كور ⚡ | فيبور ويف 🌊 | ثلاثي الأبعاد 🎧 | سلو+ريفيرب 🌙 | كاريوكي 🎤 | إير ريب 💥 | مونو 🔉",
        inline=False,
    )
    embed.add_field(
        name="🎮 أزرار لوحة التحكم",
        value=(
            "**الصف 1:** ⏮️ سابق | ⏸️▶️ إيقاف/تشغيل | ⏹️ إيقاف | ⏭️ تخطي\n"
            "**الصف 2:** 🔁 تكرار أغنية | 🔂 تكرار قائمة | 🔀 عشوائي | 🔉 صوت▼ | 🔊 صوت▲\n"
            "**الصف 3:** 📋 طابور | 🎤 كلمات | 🤖 تلقائي | 🔒 24/7"
        ),
        inline=False,
    )
    embed.set_footer(text="⏳ البوت يغادر تلقائياً بعد 15 دقيقة من عدم الاستخدام  •  إلا في وضع 24/7")
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        print("❌  DISCORD_TOKEN غير موجود في ملف .env")
    else:
        print("🚀  بدء تشغيل بوت الموسيقى…")
        bot.run(TOKEN)
