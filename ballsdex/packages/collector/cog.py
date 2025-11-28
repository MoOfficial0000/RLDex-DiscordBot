import logging

import discord
import math
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, button
from tortoise.exceptions import DoesNotExist

from typing import TYPE_CHECKING, Optional, cast

from ballsdex.core.models import BallInstance
from ballsdex.core.models import Player
from ballsdex.core.models import specials
from ballsdex.core.models import balls
from ballsdex.core.utils.transformers import BallEnabledTransform
from ballsdex.core.utils.transformers import BallTransform
from ballsdex.core.utils.transformers import SpecialEnabledTransform
from ballsdex.core.utils.transformers import SpecialTransform
from ballsdex.core.utils.buttons import ConfirmChoiceView
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.sorting import SortingChoices, sort_balls
from ballsdex.settings import settings
from ballsdex.core.utils.logging import log_action

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

# You must have a special called "Collector" and "Diamond" for this to work.
# You must be have version 2.22.0 Ballsdex or diamond will not work.

if settings.bot_name == "dragonballdex":
    # AMOUNT NEEDED FOR TOP 1 CC BALL e.g. reichtangle
    T1Req = 30

    # RARITY OF TOP 1 BALL e.g. reichtangle
    # (If not originally inputted as 1 into admin panel or /admin balls create)
    T1Rarity = 1

    # AMOUNT NEEDED FOR **MOST** COMMON CC BALL e.g. djibouti
    CommonReq = 300

    # RARITY OF MOST COMMON BALL e.g. djibouti
    # (Which was originally inputted into admin panel or /admin balls create)
    CommonRarity = 62
else:
    T1Req = 25
    T1Rarity = 1
    CommonReq = 200
    CommonRarity = 233

# ROUNDING OPTION FOR AMOUNTS NEEDED, WHAT YOU WOULD LIKE EVERYTHING TO ROUNDED TO
# e.g. Putting 10 makes everything round to the nearest 10, cc reqs would look something like:(100,110,120,130,140,150 etc)
# e.g. Putting 5 looks like: (100,105,110,115,120 etc)
# e.g. Putting 20 looks like: (100,120,140,160,180,200 etc)
# 1 is no rounding and looks like: (100,106,112,119,127 etc)
# however you are not limited to these numbers, I think Ballsdex does 50
RoundingOption = 10
# WARNINGS:
# if T1Req/CommonReq is not divisible by RoundingOption they will be affected.
# if T1Req is less than RoundingOption it will be rounded down to 0, (That's just how integer conversions work in python unfortunately)

#Same thing but for diamond
if settings.bot_name == "dragonballdex":
    dT1Req = 3
    dT1Rarity = 1
    dCommonReq = 10
    dCommonRarity = 62
else:
    dT1Req = 3
    dT1Rarity = 1
    dCommonReq = 8
    dCommonRarity = 233
dRoundingOption = 1
#no of specials req
if settings.bot_name == "dragonballdex":
    sT1Req = 27.5 # this is so from t1 it's 25 and from t3.5 it becomes 30
    sT1Rarity = 1
    sCommonReq = 100
    sCommonRarity = 62
else:
    sT1Req = 25
    sT1Rarity = 1
    sCommonReq = 80
    sCommonRarity = 233
sRoundingOption = 5

uncountablespecials = ("First natural shiny","Champion Edition Goku","Champion Edition Vegeta","Ruby","Boss","Staff","Emerald","Shiny","Mythical","Relicborne","Collector","Diamond","Xeno Goku Black","Ultra Gogito","Goku Day","Gold","Titanium White","Black","Cobalt","Crimson","Forest Green","Saffron","Sky Blue","Pink","Purple","Lime","Orange","Grey","Burnt Sienna")
log = logging.getLogger("ballsdex.packages.collector.cog")

gradient = (CommonReq-T1Req)/(CommonRarity-T1Rarity)
dgradient = (dCommonReq-dT1Req)/(dCommonRarity-dT1Rarity)
sgradient = (sCommonReq-sT1Req)/(sCommonRarity-sT1Rarity)

class Collector(commands.GroupCog):
    """
    Collector commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    ccadmin = app_commands.Group(name="admin", description="admin commands for collector")


    async def emerald(
        self,
        user,
        countryball: BallEnabledTransform,
        ):
        oneofonelist = []
        if countryball.id != 33:
            excludedspecials = uncountablespecials + ("Event Farmer",)
        else:
            excludedspecials = uncountablespecials
        missinglist = []
        if settings.bot_name == "dragonballdex":
            existinglist = ["Mythical","Collector","Diamond","Relicborne"]
        else:
            existinglist = ["Mythical","Collector","Diamond","Gold","Titanium White","Black","Cobalt","Crimson","Forest Green","Saffron","Sky Blue","Pink","Purple","Lime","Orange","Grey","Burnt Sienna"]
        extrashinies = 0
        checkfilter = {}
        for x in specials.values():
            if x.name not in excludedspecials:
                filters = {}
                filters["ball"] = countryball
                filters["special"] = x
                existcount = await BallInstance.filter(**filters).count()
                if existcount > 1:
                    existinglist.append(x.name)
                elif existcount == 1:
                    oneofonelist.append(x.name)
                else:
                    extrashinies += 1
        passed = True
        for sh in existinglist:
            cfilters = {}
            cfilters["ball"] = countryball
            cspecial = [x for x in specials.values() if x.name == sh][0]
            cfilters["special"] = cspecial
            cfilters["player__discord_id"] = user.id
            passcount = await BallInstance.filter(**cfilters).count()
            if passcount == 0:
                missinglist.append(sh)
                passed = False
        cfilters = {}
        cfilters["ball"] = countryball
        cfilters["special"]= [x for x in specials.values() if x.name == "Shiny"][0]
        cfilters["player__discord_id"] = user.id
        diamondsubtractor = int(int((dgradient*(countryball.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
        passcount = await BallInstance.filter(**cfilters).count() - diamondsubtractor
        if passcount < extrashinies and extrashinies != 0:
            if passcount < 0:
                passprogression = 0
            else:
                passprogression = passcount
            missinglist.append(f"{passprogression}/{extrashinies} Extra Shiny")
            passed = False
            extraextrashinies = 0
        else:
            extraextrashinies = passcount - extrashinies
        missingoneofones = len(oneofonelist)
        missingoneofones -= extraextrashinies
        missingonetext = []
        if missingoneofones >= 1:
            for ones in oneofonelist:
                cfilters = {}
                cfilters["ball"] = countryball
                cspecial = [x for x in specials.values() if x.name == ones][0]
                cfilters["special"] = cspecial
                cfilters["player__discord_id"] = user.id
                passcount2 = await BallInstance.filter(**cfilters).count()
                if passcount2 > 0:
                    missingoneofones -= 1
                else:
                    missingonetext.append(f"{ones} / Additional Extra Shiny")
        if missingoneofones >= 1:
            passed = False
            for mt in missingonetext:
                missinglist.append(mt)
        if passed:
            replyanswer = "passed"
        else:
            lines = "Required Specials:\n"
            missinglines = "You are currently missing:\n"
            for s in existinglist:
                lines+=f"1×`{s}`\n"
            for m in missinglist:
                missinglines+=f"`{m}`\n"
            if extrashinies != 0:
                lines+=f"{extrashinies}×`Extra Shiny`\n"
            if oneofonelist != []:
                lines+="Optional Specials that can be replaced with additional Extra Shiny **each** if not obtained:\n"
                for s in oneofonelist:
                    lines+=f"1×`{s}`\n"
                lines+=f"-# *Note: Unfinished events may become required in the near future.*\n"
            replyanswer = (f"# Emerald {countryball.country} {settings.collectible_name}:\n{lines}\n{missinglines}\n")
        return replyanswer

    async def ruby(
        self,
        user,
        countryball: BallEnabledTransform,
        ):
        collector_number = int(int((gradient*(countryball.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)
        collector_extra = math.ceil(collector_number*1.5)
        collector_total = collector_number + collector_extra
        diamond_number = int(int((dgradient*(countryball.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
        relicborne_number = math.ceil(diamond_number/1.5)
        mythical_number = int(diamond_number/2)
        specials_number = int(int((sgradient*(countryball.rarity-sT1Rarity) + sT1Req)/sRoundingOption)*sRoundingOption)
        missinglistr = []
        if settings.bot_name == "dragonballdex":
            specialsneededlist = ["1×`Emerald`","3×`Boss`",f"{mythical_number}×`Extra Mythical` [{1+mythical_number} total]",f"{relicborne_number}×`Extra Relicborne` [{1+relicborne_number} total]"]
        else:
            specialsneededlist = ["1×`Emerald`","3×`Boss`",f"{mythical_number}×`Extra Mythical` [{1+mythical_number} total]"]
        passedr = True
        basefilters = {}
        basefilters["ball"] = countryball
        basefilters["player__discord_id"] = user.id
        basecount = await BallInstance.filter(**basefilters).count()
        if basecount < collector_total:
            missinglistr.append(f"`{collector_extra} Extra`")
            passedr = False
        specialsfilters = {}
        specialsfilters["ball"] = countryball
        specialsfilters["player__discord_id"] = user.id
        specialscount = await BallInstance.filter(**specialsfilters).exclude(special=None).count()
        if specialscount < specials_number:
            missinglistr.append(f"`{specials_number} total specials`")
            passedr = False
        emeraldspecial = [x for x in specials.values() if x.name == "Emerald"][0]
        emeraldfilters = {}
        emeraldfilters["ball"] = countryball
        emeraldfilters["special"] = emeraldspecial
        emeraldfilters["player__discord_id"] = user.id
        emeraldcount = await BallInstance.filter(**emeraldfilters).count()
        if emeraldcount == 0:
            missinglistr.append("`Emerald`")
            passedr = False
        bossspecial = [x for x in specials.values() if x.name == "Boss"][0]
        bossfilters = {}
        bossfilters["ball"] = countryball
        bossfilters["special"] = bossspecial
        bossfilters["player__discord_id"] = user.id
        bosscount = await BallInstance.filter(**bossfilters).count()
        if bosscount < 3:
            missinglistr.append(f"`{bosscount}/3 Boss`")
            passedr = False
        mythicalspecial = [x for x in specials.values() if x.name == "Mythical"][0]
        mythicalfilters = {}
        mythicalfilters["ball"] = countryball
        mythicalfilters["special"]= mythicalspecial
        mythicalfilters["player__discord_id"] = user.id
        mythicalcount = await BallInstance.filter(**mythicalfilters).count()
        if mythicalcount < 1 + mythical_number:
            if mythicalcount == 0:
                mythicalprogression = 0
            else:
                mythicalprogression = mythicalcount - 1
            missinglistr.append(f"`{mythicalprogression}/{mythical_number} Extra Mythical`")
            passedr = False
        if settings.bot_name == "dragonballdex":
            relicbornespecial = [x for x in specials.values() if x.name == "Relicborne"][0]
            relicbornefilters = {}
            relicbornefilters["ball"] = countryball
            relicbornefilters["special"]= relicbornespecial
            relicbornefilters["player__discord_id"] = user.id
            relicbornecount = await BallInstance.filter(**relicbornefilters).count()
            if relicbornecount < 1 + relicborne_number:
                if relicbornecount == 0:
                    relicborneprogression = 0
                else:
                    relicborneprogression = relicbornecount - 1
                missinglistr.append(f"`{relicborneprogression}/{relicborne_number} Extra Relicborne`")
                passedr = False
        if passedr:
            replyruby = "passed"
        else:
            lines = (
                f"You need **{collector_extra} extra {countryball.country}** "
                f"(**{collector_total} total**; you currently have `{basecount}`).\n"
                f"You also need **{specials_number} total specials** (you currently have `{specialscount}`) __including Required Specials below__ to create a **Ruby character**.\n\n"
                "Required Specials:\n"
            )
            missinglines = "You are currently missing:\n"
            for s in specialsneededlist:
                lines+=f"{s}\n"
            for m in missinglistr:
                missinglines+=f"{m}\n"
            replyruby = (f"# Ruby {countryball.country} {settings.collectible_name}:\n{lines}\n{missinglines}\n")
        return replyruby
        

        
    @app_commands.command()
    @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
    @app_commands.choices(
        collector_type=[
            app_commands.Choice(name="Collector", value="Collector"),
            app_commands.Choice(name="Diamond", value="Diamond"),
            app_commands.Choice(name="Emerald", value="Emerald"),
            app_commands.Choice(name="Ruby", value="Ruby"),
        ]
    )
    async def card(
        self,
        interaction: discord.Interaction,
        countryball: BallEnabledTransform,
        collector_type: str
        ):
        """
        Get the collector card for a countryball - collector made by Kingofthehill4965, diamond/emerald/ruby by MoOfficial.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to obtain the collector card for.
        collector_type: str
            The type of card you want to claim 
        """
        if interaction.response.is_done():
            return
        assert interaction.guild
        await interaction.response.defer(ephemeral=True, thinking=True)
        if collector_type == "Emerald":
            #check if emerald exists
            checkfilter = {}
            checkspecial = [x for x in specials.values() if x.name == "Emerald"][0]
            checkfilter["special"] = checkspecial
            checkfilter["player__discord_id"] = interaction.user.id
            checkfilter["ball"] = countryball
            checkcounter = await BallInstance.filter(**checkfilter).count()
            if checkcounter >= 1:
                return await interaction.followup.send(
                    f"You already have {countryball.country} emerald card."
                )
            answerreply = await self.emerald(interaction.user, countryball)
            if answerreply == "passed":
                player, created = await Player.get_or_create(discord_id=interaction.user.id)
                await BallInstance.create(
                ball=countryball,
                player=player,
                attack_bonus=0,
                health_bonus=0,
                special=checkspecial,
                )
                await interaction.followup.send(f"Congrats! You are now a {countryball.country} emerald collector.")
            else:
                await interaction.followup.send(answerreply)
            return
        elif collector_type == "Ruby":
            #check if emerald exists
            checkfilter = {}
            checkspecial = [x for x in specials.values() if x.name == "Ruby"][0]
            checkfilter["special"] = checkspecial
            checkfilter["player__discord_id"] = interaction.user.id
            checkfilter["ball"] = countryball
            checkcounter = await BallInstance.filter(**checkfilter).count()
            if checkcounter >= 1:
                return await interaction.followup.send(
                    f"You already have {countryball.country} ruby card."
                )
            answerreply = await self.ruby(interaction.user, countryball)
            if answerreply == "passed":
                player, created = await Player.get_or_create(discord_id=interaction.user.id)
                await BallInstance.create(
                ball=countryball,
                player=player,
                attack_bonus=0,
                health_bonus=0,
                special=checkspecial,
                )
                await interaction.followup.send(f"Congrats! You are now a {countryball.country} ruby collector.")
            else:
                await interaction.followup.send(answerreply)
            return
        elif collector_type == "Diamond":
            diamond = True
        else:
            diamond = False
        filters = {}
        checkfilter = {}
        if countryball:
            filters["ball"] = countryball
        if diamond:
            special = [x for x in specials.values() if x.name == "Diamond"][0]
        else:
            special = [x for x in specials.values() if x.name == "Collector"][0]
        checkfilter["special"] = special
        checkfilter["player__discord_id"] = interaction.user.id
        checkfilter["ball"] = countryball
        checkcounter = await BallInstance.filter(**checkfilter).count()
        if checkcounter >= 1:
            if diamond:
                return await interaction.followup.send(
                    f"You already have {countryball.country} diamond card."
                )
            else:
                return await interaction.followup.send(
                    f"You already have {countryball.country} collector card."
                )
        filters["player__discord_id"] = interaction.user.id
        if diamond:
            shiny = [x for x in specials.values() if x.name == "Shiny"][0]
            filters["special"] = shiny
        balls = await BallInstance.filter(**filters).count()

        if diamond:
            collector_number = int(int((dgradient*(countryball.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
        else:
            collector_number = int(int((gradient*(countryball.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)

        country = f"{countryball.country}"
        player, created = await Player.get_or_create(discord_id=interaction.user.id)
        if balls >= collector_number:
            if diamond:
                diamondtext = " diamond"
            else:
                diamondtext = ""
            await interaction.followup.send(
                f"Congrats! You are now a {country}{diamondtext} collector.", 
                ephemeral=True
            )
            await BallInstance.create(
            ball=countryball,
            player=player,
            attack_bonus=0,
            health_bonus=0,
            special=special,
            )
        else:
            if diamond:
                text0 = "diamond"
                shinytext = " Shiny✨"
            else:
                text0 = "collector"
                shinytext = ""
            await interaction.followup.send(
                f"You need {collector_number}{shinytext} {country} to create a {text0} ball. You currently have {balls}"
            )
            
    @app_commands.command()
    @app_commands.choices(
        collector_type=[
            app_commands.Choice(name="Collector", value="Collector"),
            app_commands.Choice(name="Diamond", value="Diamond"),
            app_commands.Choice(name="Ruby", value="Ruby")
        ]
    )
    async def list(self, interaction: discord.Interaction["BallsDexBot"], collector_type: str):
        # DO NOT CHANGE THE CREDITS TO THE AUTHOR HERE!
        """
        Show the collector card list of the dex - inpsired by GamingadlerHD, made by MoOfficial.

        Parameters
        ----------
        collector_type: str
            The type of card you want to view
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        diamond=False
        ruby=False
        if collector_type == "Diamond":
            diamond = True
        if collector_type == "Ruby":
            ruby = True
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
        if diamond:
            text0 = "Diamond"
            shinytext = "✨Shinies"
        elif ruby:
            text0 = "Ruby"
            shinytext = "Extra Amount"
        else:
            text0 = "Collector"
            shinytext = "Amount"
        for collectible in sorted_collectibles:
            name = f"{collectible.country}"
            emoji = self.bot.get_emoji(collectible.emoji_id)

            if emoji:
                emote = str(emoji)
            else:
                emote = "N/A"
            if diamond:
                rarity1 = int(int((dgradient*(collectible.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
            elif ruby:
                collector_number = int(int((gradient*(collectible.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)
                collector_extra = math.ceil(collector_number*1.5)
                collector_total = collector_number + collector_extra
                diamond_number = int(int((dgradient*(collectible.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
                relicborne_number = math.ceil(diamond_number/1.5)
                mythical_number = int(diamond_number/2)
                specials_number = int(int((sgradient*(collectible.rarity-sT1Rarity) + sT1Req)/sRoundingOption)*sRoundingOption)
            else:
                rarity1 = int(int((gradient*(collectible.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)
            
            if ruby:
                if settings.bot_name == "dragonballdex":
                    entry = (name, f"{emote}{shinytext} required: **{collector_extra}** (**{collector_total} total**)\nSpecials required: **{specials_number}** including: \n`1❇️`+`3⚔️`+`{mythical_number}🌌({mythical_number+1})`+`{relicborne_number}🌠({relicborne_number+1})`")
                else:
                    entry = (name, f"{emote}{shinytext} required: **{collector_extra}** (**{collector_total} total**)\nSpecials required: **{specials_number}** including: \n`1❇️`+`3⚔️`+`{mythical_number}🌌({mythical_number+1})`")
            else:
                entry = (name, f"{emote}{shinytext} required: {rarity1}")
            entries.append(entry)
        # This is the number of countryballs which are displayed at one page,
        # you can change this, but keep in mind: discord has an embed size limit.
        per_page = 10

        source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
        source.embed.description = (
            f"__**{settings.bot_name} {text0} Card List**__"
        )
        if ruby:
            if settings.bot_name == "dragonballdex":
                source.embed.description += "\n-# Key:\n-# `1❇️`+`3⚔️`+`Extra🌌(total)`+`Extra🌠(total)`"
            else:
                source.embed.description += "\n-# Key:\n-# `1❇️`+`3⚔️`+`Extra🌌(total)`"
        source.embed.colour = discord.Colour.from_rgb(190,100,190)
        source.embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start(
            ephemeral=True,
        )

    @ccadmin.command(name="check")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    @app_commands.choices(
        option=[
            app_commands.Choice(name="Show all CCs", value="ALL"),
            app_commands.Choice(name="Show only unmet CCs", value="UNMET"),
            app_commands.Choice(name="Delete all unmet CCs", value="DELETE"), # must have full admin perm
        ]
    )
    @app_commands.choices(
        collector_type=[
            app_commands.Choice(name="Collector", value="Collector"),
            app_commands.Choice(name="Diamond", value="Diamond"),
            app_commands.Choice(name="Emerald", value="Emerald"),
            app_commands.Choice(name="Ruby", value="Ruby"),
        ]
    )
    async def check(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        option: str,
        collector_type: str,
        countryball: BallEnabledTransform | None = None,
        user: discord.User | None = None,
    ):
        """
        Check for unmet Collector Cards
        
        Parameters
        ----------
        option: str
            The type of operation you require
        collector_type: str
            The type of card you want to check
        countryball: Ball | None
        user: discord.User | None
        """
        if option == "DELETE":
            fullperm = False
            for i in settings.root_role_ids:
                if interaction.guild.get_role(i) in interaction.user.roles:
                    fullperm = True
            if fullperm == False:
                return await interaction.response.send_message(f"You do not have permission to delete {settings.plural_collectible_name}", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True, thinking=True)
        if collector_type == "Diamond":
            diamond = True
        else:
            diamond = False
        collectorspecial = [x for x in specials.values() if x.name == collector_type][0]
            
        filters = {}
        filters["special"] = collectorspecial
        if countryball:
            filters["ball"] = countryball
        if user:
            filters["player__discord_id"] = user.id

        entries = []
        unmetlist = []
        
        balls = await BallInstance.filter(**filters).prefetch_related(
                        "player","special","ball"
                    )
        if collector_type == "Diamond" or collector_type == "Collector":
            for ball in balls:
                if ball.ball.enabled == False:
                    continue
                player = await self.bot.fetch_user(int(f"{ball.player}"))
                checkfilter = {}
                checkfilter["player__discord_id"] = int(f"{ball.player}")
                checkfilter["ball"] = ball.ball
                
                if diamond:
                    checkfilter["special"] = [x for x in specials.values() if x.name == "Shiny"][0]
                    shinytext = " Shiny✨"
                else:
                    shinytext = ""
                    
                checkballs = await BallInstance.filter(**checkfilter).count()
                if checkballs == 1:
                    collectiblename = settings.collectible_name
                else:
                    collectiblename = settings.plural_collectible_name
                meetcheck = (f"{player} has **{checkballs}**{shinytext} {ball.ball} {collectiblename}")
                
                if diamond:
                    rarity2 = int(int((dgradient*(ball.ball.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
                else:
                    rarity2 = int(int((gradient*(ball.ball.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)
                    
                if checkballs >= rarity2:
                    meet = (f"**Enough to maintain ✅**\n---")
                    if option == "ALL":
                        entry = (ball.description(short=True, include_emoji=True, bot=self.bot), f"{player}({ball.player})\n{meetcheck}\n{meet}")
                        entries.append(entry)
                else:
                    meet = (f"**Not enough to maintain** ⚠️\n---")
                    entry = (ball.description(short=True, include_emoji=True, bot=self.bot), f"{player}({ball.player})\n{meetcheck}\n{meet}")
                    entries.append(entry)
                    unmetlist.append(ball)
        else:
            for ball in balls:
                if ball.ball.enabled == False:
                    continue
                player = await self.bot.fetch_user(int(f"{ball.player}"))
                if collector_type == "Emerald":
                    answerreply = await self.emerald(player, ball.ball)
                else:
                    answerreply = await self.ruby(player, ball.ball)
                if answerreply == "passed":
                    meet = (f"**Enough to maintain ✅**\n---")
                    if option == "ALL":
                        entry = (ball.description(short=True, include_emoji=True, bot=self.bot), f"{player}({ball.player})\n{meet}")
                        entries.append(entry)
                else:
                    meet = (f"**Not enough to maintain** ⚠️\n---")
                    entry = (ball.description(short=True, include_emoji=True, bot=self.bot), f"{player}({ball.player})\n{meet}")
                    entries.append(entry)
                    unmetlist.append(ball)
        if collector_type == "Diamond":
            text0 = "diamond"
            shiny0 = " shiny"
        elif collector_type == "Collector":
            text0 = "collector"
            shiny0 = ""
        elif collector_type == "Emerald":
            text0 = "emerald"
            shiny0 = " special"
        else:
            text0 = "ruby"
            shiny0 = " characters and/or special"
            
        if len(entries) == 0:
            if countryball:
                ctext = (f" {countryball}")
            else:
                ctext = ("")
            if option == "ALL":
                utext = ("")
            else:
                utext = (" unmet")
            if user == None:
                return await interaction.followup.send(f"There are no{utext}{ctext} {text0} cards!")
            else:
                return await interaction.followup.send(f"{user} has no{utext}{ctext} {text0} cards!")
            
        if option == "DELETE":
            unmetballs = ""
            for b in unmetlist:
                player = await self.bot.fetch_user(int(f"{b.player}"))
                unmetballs+=(f"{player}'s {b}\n")
            with open("unmetccs.txt", "w") as file:
                file.write(unmetballs)
            with open("unmetccs.txt", "rb") as file:
                await interaction.followup.send(f"The following {text0} cards will be deleted for no longer having enough{shiny0} {settings.plural_collectible_name} each to maintain them:",file=discord.File(file, "unmetccs.txt"),ephemeral=True)
            view = ConfirmChoiceView(
                interaction,
                accept_message=f"Confirmed, deleting...",
                cancel_message="Request cancelled.",
            )
            unmetcount = len(unmetlist)
            await interaction.followup.send(f"Are you sure you want to delete {unmetcount} {text0} card(s)?\nThis cannot be undone.",view=view,ephemeral=True)
            await view.wait()
            if not view.value:
                return
            for b in unmetlist:
                player = await self.bot.fetch_user(int(f"{b.player}"))
                try:
                    await player.send(f"Your {b.ball} {text0} card has been erased by zeno because you no longer have enough{shiny0} {settings.plural_collectible_name} to maintain it.")
                except:
                    pass
                await b.delete()
            if unmetcount == 1:
                collectiblename1 = settings.collectible_name
            else:
                collectiblename1 = settings.plural_collectible_name
            await interaction.followup.send(f"{unmetcount} {text0} card {collectiblename1} has been deleted successfully.",ephemeral=True)
            await log_action(
                f"{interaction.user} has deleted {unmetcount} {text0} card {collectiblename1} for no longer having enough{shiny0} {settings.plural_collectible_name} each to maintain them.",
                self.bot,
            )
            return
        
        else:
            per_page = 10

            source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
            source.embed.description = (
                f"__**{settings.bot_name} {collector_type} Card Check**__"
            )
            source.embed.colour = discord.Colour.from_rgb(190,100,190)

            pages = Pages(source=source, interaction=interaction, compact=True)
            await pages.start(ephemeral=True)
