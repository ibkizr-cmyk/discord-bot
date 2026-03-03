import discord
from discord.ext import commands
from discord import app_commands, ChannelType
import json
import os
import traceback

CONFIG_FILE = "config.json"

# ─────────────────────────────
# 設定ファイルの読み書き + 自動修復
# ─────────────────────────────
def load_config():
    default = {
        "intro_source": None,
        "enabled_vcs": [],
        "block_users": []
    }

    if not os.path.exists(CONFIG_FILE):
        save_config(default)
        return default

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    changed = False
    for key, value in default.items():
        if key not in data:
            data[key] = value
            changed = True

    if changed:
        save_config(data)

    return data


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


config = load_config()

# ─────────────────────────────
# Bot本体
# ─────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────
# 起動
# ─────────────────────────────
@bot.event
async def on_ready():
    print(f"{bot.user} でログインしました")
    try:
        await bot.tree.sync()
        print("スラッシュコマンド同期完了")
    except Exception as e:
        print(e)

# ─────────────────────────────
# 設定コマンド
# ─────────────────────────────

@bot.tree.command(name="set_intro_source", description="自己紹介の引用元（フォーラム or テキスト）を設定します")
async def set_intro_source(interaction: discord.Interaction, channel: discord.abc.GuildChannel):
    await interaction.response.defer()

    if not isinstance(channel, (discord.ForumChannel, discord.TextChannel)):
        await interaction.followup.send("フォーラムまたはテキストチャンネルのみ設定できます。")
        return

    config["intro_source"] = channel.id
    save_config(config)

    await interaction.followup.send(
        f"引用元を `{channel.name}` に設定しました。（タイプ: {type(channel).__name__}）"
    )


@bot.tree.command(name="add_enabled_vc", description="貼り付けを有効化するVCを追加します")
async def add_enabled_vc(interaction: discord.Interaction, vc: discord.VoiceChannel):
    await interaction.response.defer()

    if vc.id not in config["enabled_vcs"]:
        config["enabled_vcs"].append(vc.id)
        save_config(config)
        await interaction.followup.send(f"VC `{vc.name}` を貼り付け対象に追加しました。")
    else:
        await interaction.followup.send(f"VC `{vc.name}` はすでに追加されています。")


@bot.tree.command(name="remove_enabled_vc", description="貼り付け対象からVCを削除します")
async def remove_enabled_vc(interaction: discord.Interaction, vc: discord.VoiceChannel):
    await interaction.response.defer()

    if vc.id in config["enabled_vcs"]:
        config["enabled_vcs"].remove(vc.id)
        save_config(config)
        await interaction.followup.send(f"VC `{vc.name}` を貼り付け対象から削除しました。")
    else:
        await interaction.followup.send(f"VC `{vc.name}` は登録されていません。")


@bot.tree.command(name="list_enabled_vc", description="貼り付けが有効なVC一覧を表示します")
async def list_enabled_vc(interaction: discord.Interaction):
    await interaction.response.defer()

    if not config["enabled_vcs"]:
        await interaction.followup.send("貼り付けが有効なVCはありません。")
        return

    names = []
    for vc_id in config["enabled_vcs"]:
        vc = interaction.guild.get_channel(vc_id)
        if vc:
            names.append(vc.name)

    await interaction.followup.send("有効なVC:\n" + "\n".join(names))


# ─────────────────────────────
# 自己紹介取得（フォーラム or テキスト）
# ─────────────────────────────
async def get_intro_message(member: discord.Member):
    source_id = config.get("intro_source")
    if not source_id:
        return None, None

    channel = bot.get_channel(source_id)

    if isinstance(channel, discord.ForumChannel):
        threads = list(channel.threads)
        async for thread in channel.archived_threads(limit=None):
            threads.append(thread)

        for thread in threads:
            if thread.owner_id == member.id:
                async for msg in thread.history(limit=1, oldest_first=True):
                    return msg, msg.jump_url
        return None, None

    if isinstance(channel, discord.TextChannel):
        async for msg in channel.history(limit=50):
            if msg.author.id == member.id:
                return msg, msg.jump_url
        return None, None

    return None, None


# ─────────────────────────────
# VC参加イベント（例外ログ付き）
# ─────────────────────────────
@bot.event
async def on_voice_state_update(member, before, after):
    try:
        if not after.channel:
            return

        if after.channel.id not in config["enabled_vcs"]:
            return

        if member.id in config.get("block_users", []):
            return

        if after.channel.type not in (ChannelType.voice, ChannelType.stage_voice):
            return

        print(f"[DEBUG] {member} が {after.channel.name} に参加 ({after.channel.id})")

        if not after.channel.threads:
            print("[DEBUG] このVCにはチャットがありません")
            return

        vc_chat = after.channel.threads[0]

        intro_message, thread_url = await get_intro_message(member)

        if intro_message:
            intro_text = intro_message.content or "自己紹介は空です。"
        else:
            intro_text = "自己紹介がまだ登録されていません。"
            thread_url = None

        embed = discord.Embed(
            title="🎤 ボイスチャンネル参加",
            description=f"{member.mention} が **{after.channel.name}** に参加しました！",
            color=discord.Color.blue()
        )
        embed.add_field(name="📌 自己紹介", value=intro_text[:1024], inline=False)
        if thread_url:
            embed.add_field(name="🧵 自己紹介スレッド / メッセージ", value=f"[こちらから見る]({thread_url})", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")

        await vc_chat.send(embed=embed, tts=False)
        print(f"[DEBUG] メッセージ送信完了 -> {vc_chat.name} ({vc_chat.id})")

    except Exception:
        print("===== ERROR in on_voice_state_update =====")
        traceback.print_exc()
        print("==========================================")


# ─────────────────────────────
# Bot起動
# ─────────────────────────────
bot.run(os.environ["DISCORD_TOKEN"])
