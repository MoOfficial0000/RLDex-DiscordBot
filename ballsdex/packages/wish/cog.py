import logging
import time
import random
import sys
from typing import TYPE_CHECKING, Dict, cast
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands
from discord import Embed

import asyncio
import io

from ballsdex.core.models import (
    Ball,
    BallInstance,
    Player,
    specials,
    balls,
)
from ballsdex.core.utils.utils import inventory_privacy, is_staff
from ballsdex.core.models import balls as countryballs
from ballsdex.settings import settings
from ballsdex.packages.countryballs.cog import CountryBallsSpawner

from ballsdex.core.utils.transformers import (
    BallInstanceTransform,
    BallTransform,
    BallEnabledTransform,
    SpecialEnabledTransform,
)

#from ballsdex.packages.wish.xe_wish_lib import (
   # BattleBall,
   # BattleInstance,
   # gen_battle,
#)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    

log = logging.getLogger("ballsdex.packages.battle")
#THIS CODE IS A HEAVILY RESKINNED BATTLE CODE, PREPARE TO BE CONFUSED. THIS IS NOT INDENDED TO BE USED FOR OTHER DEXES EXCEPT DRAGON BALL DEX
battles = []
shenron = ["Earth Dragon Ball (1 Star)","Earth Dragon Ball (2 Star)","Earth Dragon Ball (3 Star)","Earth Dragon Ball (4 Star)","Earth Dragon Ball (5 Star)","Earth Dragon Ball (6 Star)","Earth Dragon Ball (7 Star)","Shenron"]
porunga = ["Namekian Dragon Ball (1 Star)","Namekian Dragon Ball (2 Star)","Namekian Dragon Ball (3 Star)","Namekian Dragon Ball (4 Star)","Namekian Dragon Ball (5 Star)","Namekian Dragon Ball (6 Star)","Namekian Dragon Ball (7 Star)","Porunga"]
supershenron = ["Super Dragon Ball (1 Star)","Super Dragon Ball (2 Star)","Super Dragon Ball (3 Star)","Super Dragon Ball (4 Star)","Super Dragon Ball (5 Star)","Super Dragon Ball (6 Star)","Super Dragon Ball (7 Star)","Super Shenron"]
porungadaima = ["Demon Realm Dragon Ball (1 Star)","Demon Realm Dragon Ball (2 Star)","Demon Realm Dragon Ball (3 Star)","Porunga (Daima)"]
toronbo = ["Cerealian Dragon Ball (1 Star)","Cerealian Dragon Ball (2 Star)","Toronbo"]
dragons = ["Shenron","Super Shenron","Porunga","Porunga (Daima)","Toronbo"]
ballsemojis = ["<:EarthDragonBalls:1355736004530536559>","<:SuperDragonBalls:1355736009018445854>","<:NamekianDragonBalls:1355736002135588974>","<:DemonRealmDragonBalls:1355736006782881993>","<:CerealianDragonBalls:1355735779875229867>"]
shenron1 = ["<:DB1:1355509169565859929>","<:DB2:1355509172233441473>","<:DB3:1355509175089893396>","<:DB4:1355509186871427112>","<:DB5:1355509178176897174>","<:DB6:1355509181150662766>","<:DB7:1355509183964774420>","<:Shenron:1358300433441099948>"]
porunga1 = ["<:NamekDB1:1355509351615565934>","<:NamekDB2:1355509354811625634>","<:NamekDB3:1355509357776863302>","<:NamekDB4:1355509369399152782>","<:NamekDB5:1355509360041787412>","<:NamekDB6:1355509362927341678>","<:NamekDB7:1355509365553106975>","<:Porunga:1325953103031439410>"]
supershenron1 = ["<:SuperDB1:1355509197126762498>","<:SuperDB2:1355509198875791420>","<:SuperDB3:1355509200939126914>","<:SuperDB4:1355509203380207869>","<:SuperDB5:1355509205242744903>","<:SuperDB6:1355509207331504168>","<:SuperDB7:1355509209411878933>","<:SuperShenron:1311798650246271016>"]
porungadaima1 = ["<:DemonRealmDB1:1355509715248877638>","<:DemonRealmDB2:1355509710744191134>","<:DemonRealmDB3:1355509713323819059>","<:PorungaDaima:1340039668137463941>"]
toronbo1 = ["<:CerealianDB1:1355508560284614737>","<:CerealianDB2:1355508557537218791>","<:Toronbo:1322958774088106077>"]

@dataclass
class BattleInstance:
    p1_balls: list = field(default_factory=list)
    p2_balls: list = field(default_factory=list)
    winner: str = ""
    turns: int = 0

@dataclass
class GuildBattle:
    interaction: discord.Interaction

    author: discord.Member
    opponent: int

    author_ready: bool = False
    opponent_ready: bool = False

    battle: BattleInstance = field(default_factory=BattleInstance)


def gen_deck(balls,ballinstances,maxallowed) -> str:
    """Generates a text representation of the player's deck."""
    if not balls:
        return "Empty"
    
    if maxallowed[1]=="EDB":
        dbdnames = shenron
        dbdemojis = shenron1
    elif maxallowed[1]=="SDB":
        dbdnames = supershenron
        dbdemojis = supershenron1
    elif maxallowed[1]=="NDB":
        dbdnames = porunga
        dbdemojis = porunga1
    elif maxallowed[1]=="DDB":
        dbdnames = porungadaima
        dbdemojis = porungadaima1
    elif maxallowed[1]=="CDB":
        dbdnames = toronbo
        dbdemojis = toronbo1
    if balls == "finalballs":
        balls = ["1","1","1","1","1","1","1"]
        dbdnames = balls
        dbdemojis = ["⛔","⛔","⛔","⛔","⛔","⛔","⛔"]
    if balls == "finaldragon":
        balls = ["1",]
        dbdnames = balls
        dbdemojis = [dbdemojis[-1],]
    
        
    deck_lines = [

        f"- {dbdemojis[dbdnames.index(f'{str(ball)}')]} {ballinstance}"
        for ball, ballinstance in zip(balls,ballinstances)
    ]

    deck = "\n".join(deck_lines)

    if len(deck) <= 1024:
        return deck

    total_suffix = f"\nTotal: {len(balls)}"
    suffix_length = len(total_suffix)
    max_deck_length = 1024 - suffix_length
    truncated_deck = ""
    current_length = 0
    
    for line in deck_lines:
        line_length = len(line) + (1 if truncated_deck else 0) 
        if current_length + line_length > max_deck_length:
            break
        truncated_deck += ("\n" if truncated_deck else "") + line
        current_length += line_length
    
    return truncated_deck + total_suffix

def update_embed(
    author_balls, opponent_balls, author_ogballs, opponent_ogballs, author_ready, opponent_ready, maxallowed
) -> discord.Embed:
    """Creates an embed for the battle setup phase."""
    if maxallowed[1]=="EDB":
        emoji1 = ballsemojis[0]
        emoji2 = shenron1[-1]
        rewardtext = "- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**"
    elif maxallowed[1]=="SDB":
        emoji1 = ballsemojis[1]
        emoji2 = supershenron1[-1]
        rewardtext = "**- Wild character Drop! ( ✨60% | 🌌12% )**"
    elif maxallowed[1]=="NDB":
        emoji1 = ballsemojis[2]
        emoji2 = porunga1[-1]
        rewardtext = "- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**\n- **Wild character Drop!**"
    elif maxallowed[1]=="DDB":
        emoji1 = ballsemojis[3]
        emoji2 = porungadaima1[-1]
        rewardtext = "- **Wild character Drop! ( ✨2% | 🌌0.4% )**\n- **Wild character Drop! ( ✨2% | 🌌0.4% )**\n- **Wild character Drop! ( ✨2% | 🌌0.4% )**"
    elif maxallowed[1]=="CDB":
        emoji1 = ballsemojis[4]
        emoji2 = toronbo1[-1]
        rewardtext = "- **Wild character Drop! ( ✨3% | 🌌0.6% )**\n- **Wild character Drop! ( ✨3% | 🌌0.6% )**"
    embed = discord.Embed(
        title=f"{settings.collectible_name.title()} Wishing {emoji2} {emoji1}",
        description=(
            f"Use '/wish add' and '/wish remove' to add/remove requirements\n"
            "Requires:\n"
            "-Activation Dragon (Will **not** be deleted after the wish)\n"
            "-Dragon Balls (Will be deleted after the wish)\n"
            "Click the tick button when ready.\n-------\n"
            "Rewards:\n"
            f"{rewardtext}\n"
        ),
        color=discord.Colour.from_rgb(255,255,255),
    )

    author_emoji = ":white_check_mark:" if author_ready else ":dragon:"
    opponent_emoji = ":white_check_mark:" if opponent_ready else ":EarthDragonBalls:"

    embed.add_field(
        name=f"Activation Dragon:",
        value=gen_deck(author_balls, author_ogballs,maxallowed),
        inline=True,
    )
    embed.add_field(
        name=f"Dragon Balls:",
        value=gen_deck(opponent_balls, opponent_ogballs,maxallowed),
        inline=True,
    )
    return embed


def create_disabled_buttons() -> discord.ui.View:
    """Creates a view with disabled start and cancel buttons."""
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.success, emoji="✔", label="Ready", disabled=True
        )
    )
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.danger, emoji="✖", label="Cancel", disabled=True
        )
    )


def fetch_battle(user: discord.User | discord.Member):
    """
    Fetches a wish based on the user provided.

    Parameters
    ----------
    user: discord.User | discord.Member
        The user you want to fetch the battle from.
    """
    found_battle = None

    for battle in battles:
        if user not in (battle.author, battle.opponent):
            continue

        found_battle = battle
        break

    return found_battle

class Wish(commands.GroupCog):
    """
    Wish your Dragon Balls!
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.battlerounds = []

    admin = app_commands.Group(
        name='admin', description='Admin commands for wish'
    )

    dbz = app_commands.Group(
        name='dbz', description='Completion commands for wish'
    )
    async def owned(self, player, character):
        filters = {}
        filters["ball"] = [x for x in balls.values() if x.country == f"{character}"][0]
        filters["player__discord_id"] = player
        count = await BallInstance.filter(**filters).count()
        if count == 0:
            return False
        else:
            return True
        
    @dbz.command(name="completion")
    @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
    async def completion(self, interaction: discord.Interaction, user: discord.User | None = None):
        """
        Show your dragon ball completion for wishing
        
        Parameters
        ----------
        user: discord.User
            The user whose completion you want to view, if not yours.
        """
        user_obj = user or interaction.user
        await interaction.response.defer(thinking=True)
        if user is not None:
            try:
                player = await Player.get(discord_id=user_obj.id)
            except DoesNotExist:
                await interaction.followup.send(
                    f"{user_obj.name} doesn't have any "
                    f"{extra_text}{settings.plural_collectible_name} yet."
                )
                return

            interaction_player, _ = await Player.get_or_create(discord_id=interaction.user.id)

            blocked = await player.is_blocked(interaction_player)
            if blocked and not is_staff(interaction):
                await interaction.followup.send(
                    "You cannot view the completion of a user that has blocked you.",
                    ephemeral=True,
                )
                return

            if await inventory_privacy(self.bot, interaction, player, user_obj) is False:
                return
        embed = discord.Embed(
            title=f"Wish Completion",
            description=f"Dragon Ball completion of {user_obj.mention}",
        )
        embed.color=discord.Colour.from_rgb(0,0,255)
        embed.set_author(name=user_obj, icon_url=user_obj.avatar.url)
        embed.set_footer(text="Use '/dbz completion' for the full dex completion.")

        fullresult = []
        fullset = [supershenron,shenron,porunga,porungadaima,toronbo]
        fullemojis = [supershenron1,shenron1,porunga1,porungadaima1,toronbo1]
        emojisetcount = 0
        for dbdnames in fullset:
            result = ""
            for n in range(len(dbdnames)):
                if n-1 == -1:
                    cutter=dbdnames[n-1]
                else:
                    cutter="#"+str(n)
                if await self.owned(user_obj.id,dbdnames[n-1]):
                    result += f"- :white_check_mark:{fullemojis[emojisetcount][dbdnames.index(f'{str(dbdnames[n-1])}')]}{cutter}\n"
                else:
                    result += f"- :x:{fullemojis[emojisetcount][dbdnames.index(f'{str(dbdnames[n-1])}')]}{cutter}\n"
            emojisetcount += 1
            fullresult.append(result)
            
        embed.add_field(
            name=f"Super Dragon Balls:",
            value=fullresult[0],
            inline=True,
        )
        embed.add_field(
            name=f"Earth Dragon Balls:",
            value=fullresult[1],
            inline=True,
        )
        embed.add_field(
            name=f"Namekian Dragon Balls:",
            value=fullresult[2],
            inline=True,
        )
        embed.add_field(
            name=f"Demon Realm Dragon Balls:",
            value=fullresult[3],
            inline=True,
        )
        embed.add_field(
            name=f"Cerealian Dragon Balls:",
            value=fullresult[4],
            inline=True,
        )
        
        await interaction.followup.send(
            embed=embed,
        )
    
    async def start_battle(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.followup.send(
                "This wish doesn't belong to you.", ephemeral=True
            )
            return
        
        # Set the player's readiness status

        if interaction.user == guild_battle.author:
            guild_battle.author_ready = True
            guild_battle.opponent_ready = True
        # If both players are ready, start the battle
        if not (guild_battle.battle.p1_balls and guild_battle.battle.p2_balls):
            await interaction.followup.send(
                f"Insufficient Materials!",ephemeral=True
            )
            return
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                maxallowed = bround[2]
                break
        if len(guild_battle.battle.p2_balls) != maxallowed[0]:
            await interaction.followup.send(
                f"Insufficient Materials!",ephemeral=True
            )
            return
        new_view = create_disabled_buttons()
        textvalue1 = ""
        colorvalue1 = discord.Color.green()
        for ball in guild_battle.battle.p2_balls:
            realball = await BallInstance.get(id=ball.pk).prefetch_related(
                "player"
            )
            if f"{await realball.player}" != f"{interaction.user.id}":
                textvalue1 = "⚠️ One or more Dragon Balls do not belong to you.\nThis wish has been cancelled."
                colorvalue1 = discord.Color.dark_orange()
        if textvalue1 == "":
            for ball in guild_battle.battle.p2_balls:
                realball = await BallInstance.get(id=ball.pk).prefetch_related(
                    "player"
                )
                playerr = await realball.player
                if f"{playerr}" != f"{interaction.user.id}":
                    textvalue1 = "⚠️ One or more Dragon Balls do not belong to you.\nThis wish has been cancelled."
                    colorvalue1 = discord.Color.dark_orange()
                else:
                    await realball.delete()
        noofrewards = maxallowed[0]
        if maxallowed[1]=="EDB":
            shiny_percentage = -1
            mythical_percentage = -1
        elif maxallowed[1]=="SDB":
            shiny_percentage = 60
            mythical_percentage = 10
            noofrewards = 1
        elif maxallowed[1]=="NDB":
            shiny_percentage = -1
            mythical_percentage = -1
        elif maxallowed[1]=="DDB":
            shiny_percentage = 2
            mythical_percentage = 0.4
        elif maxallowed[1]=="CDB":
            shiny_percentage = 3
            mythical_percentage = 0.6
        if textvalue1 =="":
            cog = cast("CountryBallsSpawner | None", interaction.client.get_cog("CountryBallsSpawner"))
            for i in range(noofrewards):
                resultball = await cog.countryball_cls.get_random(interaction.client)
                while f"{resultball.name}" in shenron+porunga+porungadaima+toronbo+supershenron and f"{resultball.name}" not in dragons:
                    resultball = await cog.countryball_cls.get_random(interaction.client)
                shinyresult = ""
                mythicalresult = ""
                plusatk = ""
                plushp = ""
                special = None
                shinyrng = random.randint(0,100)
                mythicalrng = random.randint(0,100)
                dasatk = int(settings.max_attack_bonus)
                dashp = int(settings.max_health_bonus)
                atkrng = random.randint(-1*dasatk, dasatk)
                if atkrng >= 0:
                    plusatk = "+"
                hprng = random.randint(-1*dashp, dashp)
                if hprng >= 0:
                    plushp = "+"
                if shinyrng <= (shiny_percentage):
                    shinyresult = f"\n***✨ It's a shiny {settings.collectible_name}! ✨***"
                    special = [x for x in specials.values() if x.name == "Shiny"][0]
                elif mythicalrng <= (mythical_percentage):
                    mythicalresult = f"\n*🔮 This {settings.collectible_name} exudes a mythical aura.🔮*"
                    special = [x for x in specials.values() if x.name == "Mythical"][0]
                statsresults = f"\n`{plusatk}{atkrng}ATK/{plushp}{hprng}HP`"
                textvalue1 += (f"{resultball.name}{statsresults}{shinyresult}{mythicalresult}\n\n")
                player, created = await Player.get_or_create(discord_id=interaction.user.id)
                instance = await BallInstance.create(
                    ball= [x for x in balls.values() if x.country == f"{resultball.name}"][0],
                    player=player,
                    special=special,
                    attack_bonus=atkrng,
                    health_bonus=hprng,
                )
        embed = discord.Embed(
            title=f"{settings.collectible_name.title()} Wishing",
            description=f"Wishing of {guild_battle.author.mention}",
            color=colorvalue1,
        )
        if textvalue1 == "⚠️ One or more Dragon Balls do not belong to you.\nThis wish has been cancelled.":
            noentry = ":no_entry_sign: "
            dragonvalue = "Cancelled"
            ballsvalue = "Cancelled"
        else:
            noentry = ""
            dragonvalue = gen_deck("finaldragon",guild_battle.battle.p1_balls,maxallowed)
            ballsvalue = gen_deck("finalballs",guild_battle.battle.p2_balls,maxallowed)
        embed.add_field(
            name=f"{noentry}Activation Dragon:",
            value=dragonvalue,
            inline=True,
        )
        embed.add_field(
            name=f"{noentry}Dragon Balls:",
            value=ballsvalue,
            inline=True,
        )
        embed.add_field(
            name="Reward:",
            value=textvalue1,
            inline=False,
        )

        await interaction.message.edit(
            content=f"{guild_battle.author.mention}'s reward(s)",
            embed=embed,
            view=new_view,
        )
        battles.pop(battles.index(guild_battle))
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                self.battlerounds.remove(bround)
                break

    async def cancel_battle(self, interaction: discord.Interaction):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "That is not your wish!", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{settings.collectible_name.title()} Wishing",
            description="The wish has been cancelled.",
            color=discord.Color.red(),
        )
        embed.add_field(
            name=f":no_entry_sign: Activation Dragon:",
            value="Cancelled",
            inline=True,
        )
        embed.add_field(
            name=f":no_entry_sign: Dragon Balls:",
            value="Cancelled",
            inline=True,
        )

        try:
            await interaction.response.defer()
        except discord.errors.InteractionResponded:
            pass

        await interaction.message.edit(embed=embed, view=create_disabled_buttons())
        battles.pop(battles.index(guild_battle))
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                self.battlerounds.remove(bround)
                break

    @app_commands.command()
    @app_commands.choices(
        dragon=[
            app_commands.Choice(name="Shenron", value="EDB"),
            app_commands.Choice(name="Super Shenron", value="SDB"),
            app_commands.Choice(name="Porunga", value="NDB"),
            app_commands.Choice(name="Porunga (Daima)", value="DDB"),
            app_commands.Choice(name="Toronbo", value="CDB"),
        ]
    )
    async def start(self, interaction: discord.Interaction, dragon: str):
        """
        Start a wish!

        Parameters
        ----------
        dragon: str
            The type of wish you would like to make.

        max_amount: int | None = 0
            The maximum amount of characters allowed each.
        """
        if fetch_battle(interaction.user) is not None:
            await interaction.response.send_message(
                "You are already wishing. You may use `/wish cancel` to cancel it.", ephemeral=True,
            )
            return
        imaginaryopponent = random.randint(0,9999999)
        battles.append(GuildBattle(interaction, interaction.user, imaginaryopponent))
        if dragon == "SDB" or dragon == "NDB" or dragon == "EDB":
            max_amount = [7,dragon]
        elif dragon == "DDB":
            max_amount = [3,dragon]
        else:
            max_amount = [2,dragon]
        self.battlerounds.append([interaction.user.id,imaginaryopponent,max_amount])
        
        embed = update_embed([], [], interaction.user.name, dragon, False, False, max_amount)

        start_button = discord.ui.Button(
            style=discord.ButtonStyle.success, emoji="✔", label="Wish"
        )
        cancel_button = discord.ui.Button(
            style=discord.ButtonStyle.danger, emoji="✖", label="Cancel"
        )

        # Set callbacks

        start_button.callback = self.start_battle
        cancel_button.callback = self.cancel_battle

        view = discord.ui.View(timeout=None)

        view.add_item(start_button)
        view.add_item(cancel_button)

        await interaction.response.send_message(
            embed=embed,
            view=view,
        )

    async def add_balls(self, interaction: discord.Interaction, countryballs):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't wishing!", ephemeral=True
            )
            return
        
        if interaction.guild_id != guild_battle.interaction.guild_id:
            await interaction.response.send_message(
                "You must be in the same server as your wish to use commands.", ephemeral=True
            )
            return
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                maxallowed = bround[2]
                break

        if maxallowed[1]=="EDB":
            if f"{await countryballs[0].ball}" not in shenron:
                await interaction.response.send_message("That is not needed for the wish you have chosen!\nPlease make sure to use the correct Dragon and Dragon Balls for this wish!", ephemeral=True)
                return
        elif maxallowed[1]=="SDB":
            if f"{await countryballs[0].ball}" not in supershenron:
                await interaction.response.send_message("That is not needed for the wish you have chosen!\nPlease make sure to use the correct Dragon and Dragon Balls for this wish!", ephemeral=True)
                return
        elif maxallowed[1]=="NDB":
            if f"{await countryballs[0].ball}" not in porunga:
                await interaction.response.send_message("That is not needed for the wish you have chosen!\nPlease make sure to use the correct Dragon and Dragon Balls for this wish!", ephemeral=True)
                return
        elif maxallowed[1]=="DDB":
            if f"{await countryballs[0].ball}" not in porungadaima:
                await interaction.response.send_message("That is not needed for the wish you have chosen!\nPlease make sure to use the correct Dragon and Dragon Balls for this wish!", ephemeral=True)
                return
        elif maxallowed[1]=="CDB":
            if f"{await countryballs[0].ball}" not in toronbo:
                await interaction.response.send_message("That is not needed for the wish you have chosen!\nPlease make sure to use the correct Dragon and Dragon Balls for this wish!", ephemeral=True)
                return
        else:
            await interaction.response.send_message("Oops, you have caught an error! please dm moofficial to fix this")
        # Determine if the user is the author or opponent and get the appropriate ball list

        user_balls = (
            guild_battle.battle.p1_balls
            if f"{await countryballs[0].ball}" in dragons
            else guild_battle.battle.p2_balls
        )


        if len(user_balls) != 0 and f"{await countryballs[0].ball}" in dragons:
            await interaction.response.send_message(
                f"You have already added the Activation Dragon!", ephemeral=True
            )
            return
        elif len(user_balls) == maxallowed[0]:
            await interaction.response.send_message(
                f"You cannot add anymore dragon balls as you have already reached the max amount limit!", ephemeral=True
            )
            return
        # Create
        for country in countryballs:
            ball = country
            # Check if ball has already been added

            if ball in user_balls:
                yield True
                continue
            for user_ball in user_balls:
                if await ball.ball == await user_ball.ball:
                    yield True
                    continue

            user_balls.append(ball)
            yield False

            p12 = []
            p22 = []
            for ball in guild_battle.battle.p1_balls:
                p12.append(await ball.ball)
            for ball in guild_battle.battle.p2_balls:
                p22.append(await ball.ball)

        # Update the battle embed for both players
        await guild_battle.interaction.edit_original_response(
            embed=update_embed(
                p12,
                p22,
                guild_battle.battle.p1_balls,
                guild_battle.battle.p2_balls,
                guild_battle.author_ready,
                guild_battle.opponent_ready,
                maxallowed,
            )
        )

    async def remove_balls(self, interaction: discord.Interaction, countryballs):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't wishing!", ephemeral=True
            )
            return
        
        if interaction.guild_id != guild_battle.interaction.guild_id:
            await interaction.response.send_message(
                "You must be in the same server as your wish to use commands.", ephemeral=True
            )
            return
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                maxallowed = bround[2]
                break

        # Determine if the user is the author or opponent and get the appropriate ball list

        user_balls = (
            guild_battle.battle.p1_balls
            if f"{await countryballs[0].ball}" in dragons
            else guild_battle.battle.p2_balls
        )
        # Create
        for country in countryballs:
            ball = country
            # Check if ball has already been added

            if ball not in user_balls:
                yield True
                continue
            
            user_balls.remove(ball)
            yield False

            p12 = []
            p22 = []
            for ball in guild_battle.battle.p1_balls:
                p12.append(await ball.ball)
            for ball in guild_battle.battle.p2_balls:
                p22.append(await ball.ball)

        # Update the battle embed for both players
        await guild_battle.interaction.edit_original_response(
            embed=update_embed(
                p12,
                p22,
                guild_battle.battle.p1_balls,
                guild_battle.battle.p2_balls,
                guild_battle.author_ready,
                guild_battle.opponent_ready,
                maxallowed,
            )
        )

    @app_commands.command()
    async def add(
        self, interaction: discord.Interaction, countryball: BallInstanceTransform, special: SpecialEnabledTransform | None = None,
    ):
        """
        Adds a countryball to a battle.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to add.
        """
        if not countryball.is_tradeable:
            await interaction.response.send_message(
                f"You cannot use this.", ephemeral=True
            )
            return
        async for dupe in self.add_balls(interaction, [countryball]):
            if dupe:
                await interaction.response.send_message(
                    f"You have already added this dragon ball!", ephemeral=True
                )
                return


        try:
            await interaction.response.send_message(
                f"Added `{countryball.description(short=True, include_emoji=False, bot=self.bot)}`!",
                ephemeral=True,
            )
        except:
            return

    @app_commands.command()
    async def remove(
        self, interaction: discord.Interaction, countryball: BallInstanceTransform, special: SpecialEnabledTransform | None = None,
    ):
        """
        Removes a countryball from battle.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        async for not_in_battle in self.remove_balls(interaction, [countryball]):
            if not_in_battle:
                await interaction.response.send_message(
                    f"You cannot remove what is not in your wish!", ephemeral=True
                )
                return


        try:
            await interaction.response.send_message(
                f"Removed `{countryball.description(short=True, include_emoji=False, bot=self.bot)}`!",
                ephemeral=True,
            )
        except:
            return
    
    @app_commands.command()
    async def cancel(
        self, interaction: discord.Interaction
    ):
        """
        Cancels the battle you are in.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't wishing!", ephemeral=True
            )
            return

        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.InteractionResponded:
            pass

        battles.pop(battles.index(guild_battle))
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                self.battlerounds.remove(bround)
                break

        await interaction.followup.send(f"Your current wish has been frozen and cancelled.",ephemeral=True)

    @admin.command(name="clear")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def clear(
        self, interaction: discord.Interaction
    ):
        """
        Cancels all wishes.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.InteractionResponded:
            pass

        battles.clear()
        self.battlerounds = []

        await interaction.followup.send(f"All wishes have been reset.",ephemeral=True)
        
