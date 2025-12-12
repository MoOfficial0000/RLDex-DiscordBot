import discord
import logging
import random
import re
import json
import os
import io
import tempfile
import traceback

from datetime import datetime, timedelta, timezone
from ballsdex.packages.countryballs.countryball import BallSpawnView
from ballsdex.packages.battle.cog import SPECIALBUFFS, checkpermit

from discord.utils import get
from discord import app_commands, File
from discord.ext import commands
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q

from ballsdex.settings import settings
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.logging import log_action
from ballsdex.settings import settings
from ballsdex.core.models import Player, BallInstance, specials, Trade, balls
from ballsdex.core.utils.transformers import (
    BallTransform,
    EconomyTransform,
    RegimeTransform,
    SpecialTransform,
    BallEnabledTransform,
    BallInstanceTransform,
    SpecialEnabledTransform,
    SpecialEnabledTransformer,
    TradeCommandType,
)

from typing import TYPE_CHECKING
from collections import Counter

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.extraPacks")

TIMEZONE_SETTING = timezone(timedelta(hours=0))

if settings.bot_name == "dragonballdex":
    currencyname = "Zeni"
    dropballs = []
    weights = []
    dropzenis = []
    zweights = [1000,500,200,100,50,20,10,5,2]

    # Add E balls
    for i in range(1, 8):
        dropballs.append(211+i)
        weights.append(15)

    # Add N balls
    for i in range(1, 8):
        dropballs.append(218+i)
        weights.append(15)

    # Add C balls
    for i in range(1, 3):
        dropballs.append(225+i)
        weights.append(7)

    # Add D balls
    for i in range(1, 4):
        dropballs.append(227+i)
        weights.append(7)

    # Add U balls
    for i in range(1, 8):
        dropballs.append(482+i) #482 main bot 239 test bot
        weights.append(6)

    # Add S balls
    for i in range(1, 8):
        dropballs.append(230+i)
        weights.append(2)

    for i in range(1, 10):
        dropzenis.append(495+i) #495 main bot 195 test bot

else:
    currencyname = "Credits"
    dropcredits = []
    cweights = [1000,500,200,100,50,20,10,5,2]
    CREDITS_NOTES = [1,2,5,10,20,50,100,200,500]
    dropballs = [
        "Sport Drop",        # 45%
        "Special Drop",      # 30%
        "Deluxe Drop",       # 14%
        "Import Drop",       # 7%
        "Exotic Drop",       # 3%
        "Black Market Drop"   # 1%
    ]

    weights = [
        45,
        30,
        14,
        7,
        3,
        1
    ]

    for i in CREDITS_NOTES:
        if i == 1:
            currencycardname = f"1 Credit"
        else:
            currencycardname = f"{i} Credits"
        currencycard = [x for x in balls.values() if x.country==currencycardname][0]
        dropcredits.append(currencycard.id)
    

class extraPacks(commands.Cog):
    """
    Simple extra commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.daily_claims = {}
        self.daily_claims_file = os.path.join(os.path.dirname(__file__), "daily_claims.json")
        self.load_daily_claims()
        self.hourly_claims = {}
        self.hourly_claims_file = os.path.join(os.path.dirname(__file__), "hourly_claims.json")
        self.load_hourly_claims()
        self.permit_users = {}

    drop = app_commands.Group(
        name='drop', description='Drop commands to open drops'
    )

    def get_random_ball(self):
        dball = random.choices(dropballs, weights=weights, k=1)[0]
        if settings.bot_name == "dragonballdex":
            return [x for x in balls.values() if x.id==dball][0]
        else:
            return [x for x in balls.values() if x.country==dball][0]

    def get_random_zeni(self):
        if settings.bot_name == "dragonballdex":
            dzeni = random.choices(dropzenis, weights=zweights, k=1)[0]
        else:
            dzeni = random.choices(dropcredits, weights=cweights, k=1)[0]
        return [x for x in balls.values() if x.id==dzeni][0]

    def get_permit(self):
        permitname = f"{currencyname} Permit"
        permitball = [x for x in balls.values() if x.country==permitname][0]
        return permitball

    def get_random_relic(self):
        return random.randint(321,324) #321,324 main bot 1,4 test bot
    
    def get_drop_tables(self):
        return {
            "Sport Drop": {"None": 100},

            "Special Drop": {
                **{color: 0.04545 for color in [
                    "Sky Blue", "Saffron", "Purple", "Pink", "Orange",
                    "Lime", "Grey", "Forest Green", "Crimson",
                    "Cobalt", "Burnt Sienna"
                ]},
                "None": 0.5
            },

            "Deluxe Drop": {
                **{color: 0.0835 for color in [
                    "Sky Blue", "Saffron", "Purple", "Pink", "Orange",
                    "Lime", "Grey", "Forest Green", "Crimson",
                    "Cobalt", "Burnt Sienna"
                ]},
                "Black": 0.0811
            },

            "Import Drop": {
                **{color: 0.05874 for color in [
                    "Sky Blue", "Saffron", "Purple", "Pink", "Orange",
                    "Lime", "Grey", "Forest Green", "Crimson",
                    "Cobalt", "Burnt Sienna"
                ]},
                "Black": 0.15410,
                "Gold": 0.09980,
                "Titanium White": 0.09980
            },

            "Exotic Drop": {
                "Shiny": 0.2274,
                "Gold": 0.3636,
                "Titanium White": 0.3636,
                "Mythical": 0.0455
            },

            "Black Market Drop": {
                "Shiny": 0.8332,
                "Mythical": 0.1668
            }
        }

    def roll_special(self, table: dict):
        items = list(table.keys())
        weights = list(table.values())
        total = sum(weights)

        r = random.random()
        cumulative = 0

        for item, weight in zip(items, weights):
            cumulative += weight / total
            if r <= cumulative:
                if item == "None":
                    return None
                return next(s for s in specials.values() if s.name == item)
            
    async def spawn_new_ball(self, user, special):
        spawn_view = await BallSpawnView.get_random(self.bot)
        newball = spawn_view.model

        atk = random.randint(-settings.max_attack_bonus, +settings.max_attack_bonus)
        hp = random.randint(-settings.max_attack_bonus, +settings.max_attack_bonus)

        player, _ = await Player.get_or_create(discord_id=user.id)

        return await BallInstance.create(
            ball=newball,
            player=player,
            special=special,
            attack_bonus=atk,
            health_bonus=hp,
        )

    async def handle_relic_drop(self, interaction, drop, drop_type, emoji):
        relic_id = self.get_random_relic()
        newball = next(b for b in balls.values() if b.id == relic_id)

        drop.ball = newball
        await drop.save()

        content, file, view = await drop.prepare_for_message(interaction)
        file.filename = "drop_card.png"
        newballdesc = drop.description(short=True, include_emoji=True, bot=self.bot)

        embed = discord.Embed(
            title=f"{drop_type} opened!",
            description=f"You opened your drop and received:\n**{newballdesc}**",
            color=discord.Color.yellow()
        )
        embed.set_image(url="attachment://drop_card.png")

        if emoji:
            embed.set_thumbnail(url=emoji.url)

        await interaction.followup.send(embed=embed, file=file)

    async def handle_zeni_drop(self, interaction, drop, drop_type, emoji):
        newball = self.get_random_zeni()

        drop.ball = newball
        await drop.save()

        content, file, view = await drop.prepare_for_message(interaction)
        file.filename = "drop_card.png"
        newballdesc = drop.description(short=True, include_emoji=True, bot=self.bot)

        embed = discord.Embed(
            title=f"{drop_type} opened!",
            description=f"You opened your drop and received:\n**{newballdesc}**",
            color=discord.Color.yellow()
        )
        embed.set_image(url="attachment://drop_card.png")

        if emoji:
            embed.set_thumbnail(url=emoji.url)

        await interaction.followup.send(embed=embed, file=file)


    async def handle_standard_drop(self, interaction, drop, drop_type, emoji):
        drop_tables = self.get_drop_tables()

        # 1. Determine special roll
        special = self.roll_special(drop_tables[drop_type])

        # 2. Generate new ball instance
        instance = await self.spawn_new_ball(interaction.user, special)

        # 3. Remove old drop
        await drop.delete()

        # 4. Prepare output card
        content, file, view = await instance.prepare_for_message(interaction)
        file.filename = "drop_card.png"

        special_name = f"{special} " if special else ""
        atk = f"+{instance.attack_bonus}" if instance.attack_bonus > 0 else instance.attack_bonus
        hp  = f"+{instance.health_bonus}" if instance.health_bonus > 0 else instance.health_bonus

        embed = discord.Embed(
            title=f"{drop_type} opened!",
            description=(
                f"You opened your drop and received:\n"
                f"**{special_name}{instance.ball}** "
                f"`(ATK:{atk}%/HP:{hp}%)`"
            ),
            color=discord.Color.yellow()
        )

        embed.set_image(url="attachment://drop_card.png")

        if emoji:
            embed.set_thumbnail(url=emoji.url)

        await interaction.followup.send(embed=embed, file=file)
    
    def load_hourly_claims(self):
        """Load hourly claim records"""
        if os.path.exists(self.hourly_claims_file):
            try:
                with open(self.hourly_claims_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, timestamp in data.items():
                        if isinstance(timestamp, str):
                            dt = datetime.fromisoformat(timestamp)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=TIMEZONE_SETTING)
                            self.hourly_claims[int(user_id)] = dt
                        else:
                            dt = datetime.fromtimestamp(timestamp, tz=TIMEZONE_SETTING)
                            self.hourly_claims[int(user_id)] = dt
            except Exception as e:
                print(f"Error occurred while loading hourly claim records: {str(e)}")
                self.hourly_claims = {}
                self.save_hourly_claims()

    def save_hourly_claims(self):
        """Save hourly claim records"""
        try:
            data = {str(uid): ts.isoformat() for uid, ts in self.hourly_claims.items()}
            with open(self.hourly_claims_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error occurred while saving hourly claim records: {str(e)}")

    
    def load_daily_claims(self):
        """Load daily claim records"""
        if os.path.exists(self.daily_claims_file):
            try:
                with open(self.daily_claims_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, timestamp in data.items():
                        if isinstance(timestamp, str):
                            dt = datetime.fromisoformat(timestamp)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=TIMEZONE_SETTING)
                            self.daily_claims[int(user_id)] = dt
                        else:
                            dt = datetime.fromtimestamp(timestamp, tz=TIMEZONE_SETTING)
                            self.daily_claims[int(user_id)] = dt
            except Exception as e:
                print(f"Error occurred while loading daily claim records: {str(e)}")
                self.daily_claims = {}
                self.save_daily_claims()

    def save_daily_claims(self):
        """Save daily claim records"""
        try:
            data = {str(uid): ts.isoformat() for uid, ts in self.daily_claims.items()}
            with open(self.daily_claims_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error occurred while saving daily claim records: {str(e)}")

    async def reqchecks(self,user_id):
        """Check for requirements"""

        #at least 10 trade partners
        trades = await Trade.filter(
            Q(player1__discord_id=user_id) | Q(player2__discord_id=user_id)
        ).values_list("player1__discord_id", "player2__discord_id")

        trade_partners = set()
        for p1, p2 in trades:
            if p1 != user_id:
                trade_partners.add(p1)
            if p2 != user_id:
                trade_partners.add(p2)
        lentrade_partners = len(trade_partners)
        compfilters = {"player__discord_id": user_id, "ball__enabled": True}
        compfilters["trade_player_id__isnull"] = True

        bot_countryballs = {x: y.id for x, y in balls.items() if y.enabled}

        owned_countryballs = set(
            x[0]
            for x in await BallInstance.filter(**compfilters)
            .distinct()  # Do not query everything
            .values_list("ball_id")
        )

        comp_percentage = round(len(owned_countryballs) / len(bot_countryballs) * 100, 1)

        return [comp_percentage,lentrade_partners]

    
    async def bulk_list_txt(self, interaction, title, items, description):
        # ----- Embed that just mentions the file -----
        embed = discord.Embed(title=title, description=description)

        # ----- Build the .txt file in memory -----
        txt_data = "\n".join(items)
        buffer = io.StringIO(txt_data)

        if settings.bot_name == "dragonballdex":
            emoji = "https://cdn.discordapp.com/emojis/1445975768080449608.png"
        else:
            emoji = "https://cdn.discordapp.com/emojis/1447386002912968825.png"

        if emoji:
                embed.set_thumbnail(url=emoji)

        # ----- Send message with embed + file -----
        await interaction.followup.send(embed=embed, file=File(buffer, filename="openedbulk.txt"))

    
    
    @app_commands.command()
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def rarity_list(self, interaction: discord.Interaction, countryball: BallEnabledTransform | None = None):
        # DO NOT CHANGE THE CREDITS TO THE AUTHOR HERE!
        """
        Show the rarities of the dex - made by GamingadlerHD

        Parameters
        ----------
        countryball: Ball | None
            The countryball you want to view it's rarity. Shows full list if not specified.
        """
        # Filter enabled collectibles
        enabled_collectibles = [x for x in balls.values() if x.enabled]

        if not enabled_collectibles:
            await interaction.response.send_message(
                f"There are no collectibles registered in {settings.bot_name} yet.",
                ephemeral=True,
            )
            return

        # Sort collectibles by rarity in ascending order
        sorted_collectibles = sorted(enabled_collectibles, key=lambda x: x.rarity)

        entries = []
        list1 = []
        list2 = []
        for collectible in sorted_collectibles:
            name = f"{collectible.country}"
            emoji = self.bot.get_emoji(collectible.emoji_id)

            if emoji:
                emote = str(emoji)
            else:
                emote = "N/A"
            # if you want the Rarity to only show full numbers like 1 or 12 use the code part here:
            # rarity = int(collectible.rarity)
            # otherwise you want to display numbers like 1.5, 5.3, 76.9 use the normal part.
            r = collectible.rarity
            if r in list2:
                list1.append(list1[-1])
            else:
                list1.append(len(list1) + 1)
            rarity = list1[-1]
            list2.append(r)

            entry = (name, f"{emote} Rarity: {rarity}")
            entries.append(entry)
            if collectible == countryball:
                return await interaction.response.send_message(
                    f"**{name}**\n{emote} Rarity: {rarity}",
                    ephemeral=True,
                )
        # This is the number of countryballs who are displayed at one page,
        # you can change this, but keep in mind: discord has an embed size limit.
        per_page = 10

        source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
        source.embed.description = (
            f"__**{settings.bot_name} rarity**__"
        )
        source.embed.colour = discord.Colour.blurple()
        source.embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start(
            ephemeral=True,
        )

        if settings.bot_name == "rocketleaguedex":
            await interaction.followup.send(f"```c\nPaint Rarities:\nTop 1. Mythical 🌌\nTop 2. Shiny ✨\nTop 3. Gold 🟨\nTop 3. Titanium White ⬜\nTop 5. Black ⬛\nTop 6. Cobalt 🟦\nTop 6. Crimson 🟥\nTop 6. Forest Green 🟩\nTop 6. Saffron 💛\nTop 6. Sky Blue 🩵\nTop 6. Pink 🩷\nTop 6. Purple 🟪\nTop 6. Lime 💚\nTop 6. Orange 🟧\nTop 6. Grey 🩶\nTop 6. Burnt Sienna 🟫\nTop 17. Unpainted ```",
            ephemeral=True,
        )

    @app_commands.command()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def special_buffs(self, interaction: discord.Interaction):
        """
        Display all special buffs.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        specials = await SpecialEnabledTransformer().load_items()

        bot_key = "dragonballdex" if settings.bot_name == "dragonballdex" else "rocketleaguedex"

        user_id = interaction.user.id
        has_permit = await checkpermit(self, user_id, interaction)

        if has_permit:
            users_permit = self.permit_users[user_id]
            users_buff = users_permit.attack_bonus
            buff_multiplier = users_buff/100 + 1
        else:
            buff_multiplier = 1
            
        entries = []
        for sp in specials:
            name = f"{sp.name}" if sp.name else "None"
            emoji = sp.emoji
            fullname = f"{emoji}{name}"
            buff = SPECIALBUFFS.get(name, {}).get(bot_key, 0)
            your_buff = int(buff*buff_multiplier)
            if your_buff == buff:
                entry = (fullname, f"Buff: +{buff}")
            else:
                entry = (fullname, f"Base Buff: +{buff}\nYour Buff: **+{your_buff}** ⚡")
            entries.append(entry)
        # This is the number of countryballs who are displayed at one page,
        # you can change this, but keep in mind: discord has an embed size limit.
        per_page = 10

        source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
        source.embed.description = (
            f"__**Special Buffs**__\n-# Use `/upgrade buffs` to upgrade your special buffs!"
        )
        source.embed.colour = discord.Color.from_rgb(255,239,71)
        source.embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start(
            ephemeral=True,
        )

    @app_commands.command()
    @app_commands.checks.cooldown(1, 120, key=lambda i: i.user.id)
    async def daily(self, interaction: discord.Interaction):
        """
        Daily check-in to claim rewards.
        """
        #must be main server
        if interaction.guild.id not in settings.admin_guild_ids:
            await interaction.response.send_message(
                f"Daily and hourly commands can only be used in the main server.\nJoin now: {settings.discord_invite}",
                ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)

        #reqchecker
        compreq = False
        tradereq = False
        reqnumbers = await self.reqchecks(interaction.user.id)
        comp_percentage = reqnumbers[0]
        lentrade_partners = reqnumbers[1]
        if comp_percentage >= 10:
            compreq = True
        if lentrade_partners >= 10:
            tradereq = True
        if tradereq == False or compreq == False:
            def falsecheck(bool):
                if bool == False:
                    return ":x:"
                else:
                    return ":white_check_mark:"
            await interaction.followup.send(
                f":warning: You don't meet all the requirements for daily and hourly commands! :warning:\n\n"
                f"Requirements:\n"
                f"Minimum 10% self-caught completion {falsecheck(compreq)}\n-# (You currently have **{comp_percentage}%**)\n"
                f"At least 10 users traded with {falsecheck(tradereq)}\n-# (You currently have **{lentrade_partners}**)"
                )
            return
            
        #main
        user_id = interaction.user.id
        now = datetime.now(TIMEZONE_SETTING)
        
        if user_id in self.daily_claims:
            last_claim = self.daily_claims[user_id]
            if last_claim.tzinfo is None:
                last_claim = last_claim.replace(tzinfo=TIMEZONE_SETTING)
            next_claim = last_claim + timedelta(days=1)
            
            if now <= next_claim:
                time_left = next_claim - now
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                await interaction.followup.send(
                    f"You have already claimed today's reward!\n"
                    f"Please try again in {hours} hours and {minutes} minutes.",
                    ephemeral=True
                )
                return
            
        try:
            recievedtext = ""
            if settings.bot_name == "dragonballdex":
                for i in range(3):
                    relicorzeni = "Zeni Drop" if random.random() < 0.75 else "Relic Drop"
                    ball = [x for x in balls.values() if x.country == relicorzeni][0]
                    instance = await BallInstance.create(
                        ball=ball,
                        player=player,
                        special=None,
                        attack_bonus=0,
                        health_bonus=0,
                    )
                    recievedtext += f"\n**{ball.country}**"
                emoji = "https://cdn.discordapp.com/emojis/1445975768080449608.png"
            else:
                for i in range(3):
                    ball = [x for x in balls.values() if x.country == "Credits Drop"][0] if random.random() < 0.75 else self.get_random_ball()
                    instance = await BallInstance.create(
                        ball=ball,
                        player=player,
                        special=None,
                        attack_bonus=0,
                        health_bonus=0,
                    )
                    recievedtext += f"\n**{ball.country}**"
                emoji = "https://cdn.discordapp.com/emojis/1447386002912968825.png"
            
            self.daily_claims[user_id] = now
            self.save_daily_claims()

            embed = discord.Embed(
                title="🎁 Daily Check-in Reward",
                description=f"Congratulations on claiming your daily reward!\nYou received: {recievedtext}",
                color=discord.Color.green()
            )
            if emoji:
                embed.set_thumbnail(url=emoji)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Error occurred while distributing daily reward: {str(e)}")
            traceback.print_exc()
            await interaction.followup.send(
                "An error occurred while distributing the reward. Please try again later!",
                ephemeral=True
            )

    @app_commands.command()
    @app_commands.checks.cooldown(1, 120, key=lambda i: i.user.id)
    async def hourly(self, interaction: discord.Interaction):
        """
        Hourly check-in to claim rewards.
        """
        #must be main server
        if interaction.guild.id not in settings.admin_guild_ids:
            await interaction.response.send_message(
                f"Daily and hourly commands can only be used in the main server.\nJoin now: {settings.discord_invite}",
                ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)

        #reqchecker
        compreq = False
        tradereq = False
        reqnumbers = await self.reqchecks(interaction.user.id)
        comp_percentage = reqnumbers[0]
        lentrade_partners = reqnumbers[1]
        if comp_percentage >= 10:
            compreq = True
        if lentrade_partners >= 10:
            tradereq = True
        if tradereq == False or compreq == False:
            def falsecheck(bool):
                if bool == False:
                    return ":x:"
                else:
                    return ":white_check_mark:"
            await interaction.followup.send(
                f":warning: You don't meet all the requirements for daily and hourly commands! :warning:\n\n"
                f"Requirements:\n"
                f"10% self-caught completion {falsecheck(compreq)}\n-# (You currently have **{comp_percentage}%**)\n"
                f"At least 10 users traded with {falsecheck(tradereq)}\n-# (You currently have **{lentrade_partners}**)"
                )
            return
            
        #main
        user_id = interaction.user.id
        now = datetime.now(TIMEZONE_SETTING)
        
        if user_id in self.hourly_claims:
            last_claim = self.hourly_claims[user_id]
            if last_claim.tzinfo is None:
                last_claim = last_claim.replace(tzinfo=TIMEZONE_SETTING)

            # 1 hour cooldown
            next_hour = last_claim + timedelta(hours=1)

            if now < next_hour:
                time_left = next_hour - now
                minutes = int(time_left.total_seconds() // 60)
                seconds = int(time_left.total_seconds() % 60)

                await interaction.followup.send(
                    f"You have already claimed your hourly reward!\n"
                    f"Please try again in {minutes} minutes and {seconds} seconds.",
                    ephemeral=True
                )
                return
            
        try:
            ball = self.get_random_ball()
            
            instance = await BallInstance.create(
                ball=ball,
                player=player,
                special=None,
                attack_bonus=0,
                health_bonus=0,
            )
            
            self.hourly_claims[user_id] = now
            self.save_hourly_claims()
            
            embed = discord.Embed(
                title="⏰ Hourly Reward",
                description=f"Congratulations on claiming your hourly reward!\nYou received: **{ball.country}**",
                color=discord.Color.green()
            )
            emoji = self.bot.get_emoji(ball.emoji_id)
            if emoji:
                embed.set_image(url=emoji.url)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Error occurred while distributing hourly reward: {str(e)}")
            traceback.print_exc()
            await interaction.followup.send(
                "An error occurred while distributing the reward. Please try again later!",
                ephemeral=True
            )

    @drop.command(name="open")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def open(self, interaction: discord.Interaction, drop: BallInstanceTransform):
        """Open a drop."""

        # -----------------------------------
        # 1. EPHEMERAL VALIDATION (before defer)
        # -----------------------------------
        if await drop.is_locked():
            return await interaction.response.send_message(
                "This is currently locked for a trade. Please try again later.",
                ephemeral=True
            )

        ball = await drop.ball
        drop_type = ball.country

        # DragonBallDex relic validation
        if settings.bot_name == "dragonballdex" and drop_type not in ("Relic Drop","Zeni Drop"):
            return await interaction.response.send_message(
                "You must select a valid Drop!",
                ephemeral=True
            )

        # Standard drop type validity check
        if settings.bot_name != "dragonballdex":
            drop_tables = self.get_drop_tables()
            if drop_type not in drop_tables and drop_type != "Credits Drop":
                return await interaction.response.send_message(
                    "You must select a valid drop!",
                    ephemeral=True
                )

        # -----------------------------------
        # 2. PUBLIC DEFER (reward message will be public)
        # -----------------------------------
        await interaction.response.defer(thinking=True)

        emoji = self.bot.get_emoji(ball.emoji_id)

        # -----------------------------------
        # 3. Execute correct drop handler
        # -----------------------------------
        if settings.bot_name == "dragonballdex":
            if drop_type == "Relic Drop":
                await self.handle_relic_drop(interaction, drop, drop_type, emoji)
            else:
                await self.handle_zeni_drop(interaction, drop, drop_type, emoji)
        else:
            if drop_type != "Credits Drop":
                await self.handle_standard_drop(interaction, drop, drop_type, emoji)
            else:
                await self.handle_zeni_drop(interaction, drop, drop_type, emoji)

    @drop.command(name="bulk_open")
    @app_commands.checks.cooldown(1, 120, key=lambda i: i.user.id)
    async def bulk_open(self, interaction: discord.Interaction):
        """Bulk open all your drops."""
        await interaction.response.defer(thinking=True)
        fulldrops = []
        dropprocess = []
        dropdescription = f"You recieved:\n"
        lockeddrops = 0
        totalzeni = 0
        if settings.bot_name == "dragonballdex":
            dropnames = ["Relic Drop","Zeni Drop"]
            dbrelics = []
        else:
            dropnames = ["Sport Drop","Special Drop","Deluxe Drop","Import Drop","Exotic Drop","Black Market Drop","Credits Drop"]
            rlspecials = []
        for dropname in dropnames:
            drfilters = {}
            drfilters["ball"] = [x for x in balls.values() if x.country == dropname][0]
            drfilters["player__discord_id"] = interaction.user.id
            fulldrops += await BallInstance.filter(**drfilters).prefetch_related("ball")
        numberofdrops = len(fulldrops)
        if numberofdrops < 2:
            await interaction.followup.send("You need to have at least 2 drops to use `/drop bulk_open`")
            return
        for drop in fulldrops:
            if await drop.is_locked():
                dropdesc = drop.description(short=True, include_emoji=False, bot=self.bot)
                numberofdrops -= 1
                lockeddrops += 1
                dropprocess.append(f"{dropdesc} is currently locked for a trade.")
                continue
            dropcountry = drop.ball.country
            newcountry = ""
            if dropcountry == "Relic Drop":
                relic_id = self.get_random_relic()
                newball = next(b for b in balls.values() if b.id == relic_id)
                drop.ball = newball
                await drop.save()
                newcountry = drop.ball.country
                dbrelics.append(newcountry)
            elif dropcountry == "Zeni Drop" or dropcountry == "Credits Drop":
                newball = self.get_random_zeni()
                drop.ball = newball
                await drop.save()
                newcountry = drop.ball.country
                totalzeni += drop.ball.health
            else:
                drop_tables = self.get_drop_tables()
                special = self.roll_special(drop_tables[dropcountry])
                instance = await self.spawn_new_ball(interaction.user, special)
                await drop.delete()
                if special == None:
                    specialname = "None"
                    specialemoji = ""
                else:
                    specialname = special.name
                    specialemoji = f"{special.emoji} "
                newcountry = f"{specialemoji}{instance.ball}"
                rlspecials.append(specialname)
            dropprocess.append(f"{dropcountry} ---> {newcountry}")
        droptitle = f"{numberofdrops} Drops Opened!"
        if settings.bot_name == "dragonballdex":
            reliccounts = Counter(dbrelics)
            relic_names = [
                ("Relic of Divinity","<:RelicOfDivinity:1446356216409489561>"),
                ("Relic of Monarchy","<:RelicOfMonarchy:1446356217537757276>"),
                ("Relic of Destruction","<:RelicOfDestruction:1446356227218083850>"),
                ("Relic of Tyranny","<:RelicOfTyranny:1446356219106431067>"),
            ]
            for relic, emoji in relic_names:
                count = reliccounts[relic]
                if count > 0:
                    dropdescription += f"**{count}× {emoji} {relic}**\n"
        else:
            specialcounts = Counter(rlspecials)
            special_names = [
                ("Sky Blue", "🩵"),
                ("Saffron", "💛"),
                ("Purple", "🟪"),
                ("Pink", "🩷"),
                ("Orange", "🟧"),
                ("Lime", "💚"),
                ("Grey", "🩶"),
                ("Forest Green", "🟩"),
                ("Crimson", "🟥"),
                ("Cobalt", "🟦"),
                ("Burnt Sienna", "🟫"),
                ("Black", "⬛"),
                ("Titanium White", "⬜"),
                ("Gold", "🟨"),
                ("Shiny", "✨"),
                ("Mythical", "🌌"),
            ]
            for name, emoji in special_names:
                count = specialcounts[name]
                if count > 0:
                    dropdescription += f"**{count}× {emoji} {name}**\n"
            nonecount = specialcounts["None"]
            if nonecount > 0:
                dropdescription += f"**{nonecount}× Unpainted**\n"
        if totalzeni > 0:
            dropdescription += f"**Total {currencyname}: {totalzeni}**\n"
        if lockeddrops > 0:
            dropdescription += f"*{lockeddrops} drop(s) failed to open. (Locked for trade)*"
        await self.bulk_list_txt(interaction,droptitle,dropprocess,dropdescription)


