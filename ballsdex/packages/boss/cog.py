import discord
import time
import random
import string
import logging
import re

from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING, Optional, cast
from discord.ui import Button, View

from ballsdex.settings import settings
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.core.utils.transformers import BallEnabledTransform
from ballsdex.core.utils.transformers import SpecialTransform, BallTransform
from ballsdex.core.utils.transformers import SpecialEnabledTransform
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.logging import log_action
from ballsdex.settings import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.boss.cog")
FILENAME_RE = re.compile(r"^(.+)(\.\S+)$")

from ballsdex.core.models import (
    Ball,
    BallInstance,
    BlacklistedGuild,
    BlacklistedID,
    GuildConfig,
    Player,
    Trade,
    TradeObject,
    balls,
    specials,
)

# IMPORTANT NOTES, READ BEFORE USING
# 1. YOU MUST HAVE A SPECIAL CALLED "Boss" IN YOUR DEX, THIS IS FOR REWARDING THE WINNER.
#    MAKE IT SO THE SPECIAL'S END DATE IS BEFORE TODAY'S DATE
# 2. ONLY USE A COUNTRYBALL AS A BOSS in /boss start IF IT HAS BOTH THE COLLECTIBLE AND WILD CARDS STORED,
#    OTHERWISE THIS WILL RESULT TO AN ERROR.
#    Sometimes, you might create a non-spawnable ball using /admin balls create command, if that's the case
#    there's a chance you may have not selected a wild card as it isn't required.
#    Cards without wild cards do not work as a boss, as again, this will result in an error.
#    If you are using a ball made from the admin panel for the boss, then it's fine, since admin panel requires wild card.
# 3. You may change the shiny buffs below to suit your dex better, it's defaulted at 1000 HP & ATK Bonus
# 4. Please report all bugs to user @moofficial on discord

# HOW TO PLAY
# Some commands can only be used by admins, these control the boss actions.
# 1. Start the boss using /boss start command. (ADMINS ONLY)
#    Choose a countryball to be the boss (required). Choose HP (Optional, Defaulted at 40000)
# 2. Players can join using /boss join command.
# 3. Start a round using /boss defend or /boss attack.(ADMINS ONLY)
#    With /boss attack you can choose how much attack the boss deals (Required)
# 4. Players now choose an item to use against the boss using /boss select
# 5. /boss end_round ends the current round and displays user permformance about the round (ADMIN ONLY)
# 6. Step 3-5 is repeated until the boss' HP runs out, but you can end early with Step 7.
# 7. /boss_conclude ends the boss battle and rewards the winner, but you can choose to *not* reward the winner (ADMIN ONLY)


@app_commands.guilds(*settings.admin_guild_ids)
class Boss(commands.GroupCog):
    """
    Boss commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.boss_enabled = False
        self.balls = []
        self.users = []
        self.usersdamage = []
        self.usersinround = []
        self.currentvalue = ("")
        self.bossHP = 0
        self.picking = False
        self.round = 0
        self.attack = False
        self.bossattack = 0
        self.bossball = None
        self.bosswild = None
        self.disqualified = []

    bossadmin = app_commands.Group(name="admin", description="admin commands for boss")

    @bossadmin.command(name="start")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def start(self, interaction: discord.Interaction, ball: BallTransform, hp_amount: int):
        """
        Start the boss
        """
        if self.boss_enabled == True:
            return await interaction.response.send_message(f"There is already an ongoing boss battle", ephemeral=True)
        self. = hp_amount
        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = ball.collection_card.split(".")[-1]
        file_location = "." + ball.collection_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.response.send_message((f"# The boss battle has begun!\n-# HP: {self.bossHP} Credits: nobodyboy (Card Art)"),file=discord.File(file_location, filename=file_name),)
        await interaction.followup.send("Use `/boss join` to join the battle!")
        if ball != None:
            self.boss_enabled = True
            self.bossball = ball

            extension = ball.wild_card.split(".")[-1]
            file_location = "." + ball.wild_card
            file_name = f"nt_{generate_random_name()}.{extension}"
            self.bosswild = file=discord.File(file_location, filename=file_name)

    @bossadmin.command(name="attack")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def attack(self, interaction: discord.Interaction, attack_amount: int | None = None):
        """
        Start a round where the Boss Attacks
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if self.picking:
            return await interaction.response.send_message("There is already an ongoing round", ephemeral=True)
        if len(self.users) == 0:
            return await interaction.response.send_message("There are not enough users to start the round", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.response.send_message("The Boss is dead", ephemeral=True)
        self.round += 1

        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = self.bossball.wild_card.split(".")[-1]
        file_location = "." + self.bossball.wild_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.response.send_message(
            (f"Round {self.round}\n# {self.bossball.country} is preparing to attack!"),file=discord.File(file_location, filename=file_name)
        )
        await interaction.followup.send(f"Use `/boss select` to select your defending {settings.collectible_name}.\nYour selected {settings.collectible_name}'s HP will be used to defend.")
        self.picking = True
        self.attack = True
        self.bossattack = (attack_amount if attack_amount is not None else random.randrange(0, 10000, 500))

    @bossadmin.command(name="defend")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def defend(self, interaction: discord.Interaction):
        """
        Start a round where the Boss Defends
        """
        
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if self.picking:
            return await interaction.response.send_message("There is already an ongoing round", ephemeral=True)
        if len(self.users) == 0:
            return await interaction.response.send_message("There are not enough users to start the round", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.response.send_message("The Boss is dead", ephemeral=True)
        self.round += 1

        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = self.bossball.wild_card.split(".")[-1]
        file_location = "." + self.bossball.wild_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.response.send_message(
            (f"Round {self.round}\n# {self.bossball.country} is preparing to defend!"),file=discord.File(file_location, filename=file_name)
        )
        await interaction.followup.send(f"Use `/boss select` to select your attacking {settings.collectible_name}.\nYour selected {settings.collectible_name}'s ATK will be used to attack.")
        self.picking = True
        self.attack = False


    @bossadmin.command(name="end_round")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def end_round(self, interaction: discord.Interaction):
        """
        End the current round
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if not self.picking:
            return await interaction.response.send_message(
                f"There are no ongoing rounds, use `/boss attack` or `/boss defend` to start one", ephemeral=True
            )
        self.picking = False
        if not self.attack:
            if int(self.bossHP) <= 0:
                await interaction.response.send_message(
                    f"{self.currentvalue}There is 0 HP remaining on the boss, the boss has been defeated!",
                )
            else:
                await interaction.response.send_message(
                    f"{self.currentvalue}There is {self.bossHP} HP remaining on the boss",
                )
        else:
            snapshotusers = self.users.copy()
            for user in snapshotusers:
                if str(user) not in self.currentvalue:
                    self.currentvalue += ("<@"+str(user)+"> has not picked on time and ***died!***\n")
                    self.users.remove(user)
            if len(self.users) == 0:
                await interaction.response.send_message(
                    f"The boss has dealt {self.bossattack} damage!\n{self.currentvalue}The boss has won!",
                )
            else:
                await interaction.response.send_message(
                    f"The boss has dealt {self.bossattack} damage!\n{self.currentvalue}",
                )
        self.currentvalue = ("")

    @bossadmin.command(name="stats")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def stats(self, interaction: discord.Interaction):
        """
        See current stats of the boss
        """
        with open("stats.txt","w") as file:
            file.write(f"Boss:{self.bossball}\nCurrentValue:{self.currentvalue}\nUsers:{self.users}\n\nUsersDamage:{self.usersdamage}\n\nBalls:{self.balls}\n\nUsersInRound:{self.usersinround}")
        with open("stats.txt","rb") as file:
            return await interaction.response.send_message(file=discord.File(file,"stats.txt"), ephemeral=True)

    @bossadmin.command(name="disqualify")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def disqualify(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        user_id : str | None = None,
        ):
        """
        Disqualify a member from the boss
        """
        if (user and user_id) or (not user and not user_id):
            await interaction.response.send_message(
                "You must provide either `user` or `user_id`.", ephemeral=True
            )
            return

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))  # type: ignore
            except ValueError:
                await interaction.response.send_message(
                    "The user ID you gave is not valid.", ephemeral=True
                )
                return
            except discord.NotFound:
                await interaction.response.send_message(
                    "The given user ID could not be found.", ephemeral=True
                )
                return
        else:
            user_id = user.id

        if int(user_id) not in self.users:
            await interaction.response.send_message(
                f"{user} is not in the Battle.", ephemeral=True
            )
            return
        else:
            self.users.remove(int(user_id))
            self.disqualified.append(int(user_id))
            await interaction.response.send_message(
                f"{user} has been disqualified successfully.", ephemeral=True
            )
            return


    @app_commands.command()
    async def select(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
        special: SpecialEnabledTransform | None = None,
        shiny: bool | None = None,
    ):
        """
        Select countryball to use against the boss.
        
        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to select
        special: Special
            Filter the results of autocompletion to a special event. Ignored afterwards.
        shiny: bool
            Filter the results of autocompletion to shinies. Ignored afterwards.
        """
        if [int(interaction.user.id),self.round] in self.usersinround:
            return await interaction.response.send_message(
                f"You have already selected an {settings.collectible_name}", ephemeral=True
            )
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if not self.picking:
            return await interaction.response.send_message(f"It is not yet time to select an {settings.collectible_name}", ephemeral=True)
        if interaction.user.id not in self.users:
            return await interaction.response.send_message(
                "You did not join, or you're dead/disqualified.", ephemeral=True
            )
        if not ball.is_tradeable:
            await interaction.response.send_message(
                f"You cannot use this {settings.collectible_name}.", ephemeral=True
            )
            return
        if ball in self.balls:
            return await interaction.response.send_message(
                f"You cannot select the same {settings.collectible_name} twice", ephemeral=True
            )
        if ball == None:
            return
        self.balls.append(ball)
        self.usersinround.append([int(interaction.user.id),self.round])
        if settings.bot_name == "dragonballdex":
            maxvalue = 180000
            shinyvalue = 20000
            mythicalvalue = 50000
            bossvalue = 30000
            eventvalue1 = 10000
            eventvalue2 = 7000
        else:
            maxvalue = 14000
            shinyvalue = 5000
            mythicalvalue = 12000
            bossvalue = 6000
            eventvalue1 = 3000
            eventvalue2 = 2000
        if ball.attack > maxvalue:
            ballattack = maxvalue
        elif ball.attack < 0:
            ballattack = 0
        else:
            ballattack = ball.attack
        if ball.health > maxvalue:
            ballhealth = maxvalue
        elif ball.health < 0:
            ballhealth = 0
        else:
            ballhealth = ball.health

        messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack} ATK and {ballhealth} HP"
        if "✨" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+{shinyvalue} ATK and {ballhealth}+{shinyvalue} HP"
            ballhealth += shinyvalue
            ballattack += shinyvalue
        elif "🌌" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+{mythicalvalue} ATK and {ballhealth}+{mythicalvalue} HP"
            ballhealth += mythicalvalue
            ballattack += mythicalvalue
        elif "🟨" in messageforuser or "⬜" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+1500 ATK and {ballhealth}+1500 HP"
            ballhealth += 1500
            ballattack += 1500
        elif "⬛" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+1250 ATK and {ballhealth}+1250 HP"
            ballhealth += 1250
            ballattack += 1250
        elif "🟦" in messageforuser or "🟥" in messageforuser or "🟩" in messageforuser or "💛" in messageforuser or "🩵" in messageforuser or "🟪" in messageforuser or "💚" in messageforuser or "🟧" in messageforuser or "🩶" in messageforuser or "🟫" in messageforuser or "🩷" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+1000 ATK and {ballhealth}+1000 HP"
            ballhealth += 1000
            ballattack += 1000
        elif "🚀" in messageforuser or "🎩" in messageforuser or "🐑" in messageforuser or "🔮" in messageforuser or "🇺🇸" in messageforuser :
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+{eventvalue1} ATK and {ballhealth}+{eventvalue1} HP"
            ballhealth += eventvalue1
            ballattack += eventvalue1
        elif "☀" in messageforuser or "☀️" in messageforuser or "🎃" in messageforuser or "🔵" in messageforuser or "🔴" in messageforuser or "🐉" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+{eventvalue2} ATK and {ballhealth}+{eventvalue2} HP"
            ballhealth += eventvalue2
            ballattack += eventvalue2
        elif "⚔️" in messageforuser or "⚔" in messageforuser or "🏆" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+{bossvalue} ATK and {ballhealth}+{bossvalue} HP"
            ballhealth += bossvalue
            ballattack += bossvalue
        else:
            pass
            
        if not self.attack:
            self.bossHP -= ballattack
            self.usersdamage.append([int(interaction.user.id),ballattack])
            self.currentvalue += ("<@"+str(interaction.user.id)+">'s "+str(ball.description(short=True, include_emoji=True, bot=self.bot))+" has dealt "+(str(ballattack))+" damage!\n")
        else:
            if self.bossattack >= ballhealth:
                self.users.remove(interaction.user.id)
                self.currentvalue += ("<@"+str(interaction.user.id)+">'s "+str(ball.description(short=True, include_emoji=True, bot=self.bot))+" had "+(str(ballhealth))+"HP and ***died!***\n")
            else:
                self.currentvalue += ("<@" + str(interaction.user.id) + ">'s " + str(ball.description(short=True, include_emoji=True, bot=self.bot)) + " had " + (str(ballhealth)) + "HP and ***survived!***\n")

        await interaction.response.send_message(
            messageforuser, ephemeral=True
        )
        await log_action(
            f"-# Round {self.round}\n{interaction.user}'s {messageforuser}\n-# -------",
            self.bot,
        )

    @bossadmin.command(name="conclude")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def conclude(self, interaction: discord.Interaction, do_not_reward: bool | None = False,):
        """
        Finish the boss, conclude the Winner
        """
        self.picking = False
        self.boss_enabled = False
        test = self.usersdamage
        test2 = []
        total = ("")
        totalnum = []
        for i in range(len(test)):
            if test[i][0] not in test2 and test[i][0] in self.users:
                temp = 0
                tempvalue = test[i][0]
                test2.append(tempvalue)
                for j in range(len(test)):
                    if test[j][0] == tempvalue:
                        temp += test[j][1]
                total += ("<@" + str(tempvalue) + "> has dealt a total of " + str(temp) + " damage!\n")
                totalnum.append([tempvalue, temp])
        bosswinner = 0
        highest = 0
        for k in range(len(totalnum)):
            if totalnum[k][1] > highest:
                highest = totalnum[k][1]
                bosswinner = totalnum[k][0]
        if bosswinner == 0:
            self.round = 0
            self.balls = []
            self.users = []
            self.currentvalue = ("")
            self.usersdamage = []
            self.usersinround = []
            self.bossHP = 0
            self.round = 0
            self.attack = False
            self.bossattack = 0
            self.bossball = None
            self.bosswild = None
            self.disqualified = []
            return await interaction.response.send_message(f"BOSS HAS CONCLUDED\nThe boss has won the Boss Battle!")
        if do_not_reward == False:
            await interaction.response.defer(thinking=True)
            player, created = await Player.get_or_create(discord_id=bosswinner)
            special = special = [x for x in specials.values() if x.name == "Boss"][0]
            instance = await BallInstance.create(
                ball=self.bossball,
                player=player,
                shiny=False,
                special=special,
                attack_bonus=0,
                health_bonus=0,
            )
            await interaction.followup.send(
                f"BOSS HAS CONCLUDED.\n{total}\n<@{bosswinner}> has won the Boss Battle!\n\n"
                f"`{self.bossball}` {settings.collectible_name} was successfully given to *<@{bosswinner}>*.\n"
                f"ATK:`0` • Special: `Boss`\n"
                f"HP:`0` • Shiny: `None`"
            )
            await log_action(
                f"`BOSS REWARDS` gave {settings.collectible_name} {self.bossball.country} to the winner. "
                f"Special=Boss ATK=0 "
                f"HP=0 shiny=None",
                self.bot,
            )
        else:
            await interaction.response.send_message(f"BOSS HAS CONCLUDED.\n{total}\n<@{bosswinner}> has won the Boss Battle!\n\n")
        self.round = 0
        self.balls = []
        self.users = []
        self.currentvalue = ("")
        self.usersdamage = []
        self.usersinround = []
        self.bossHP = 0
        self.round = 0
        self.attack = False
        self.bossattack = 0
        self.bossball = None
        self.bosswild = None
        self.disqualified = []

    @app_commands.command()
    async def join(self, interaction: discord.Interaction):
        """
        Join the boss battle!.
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if int(interaction.user.id) in self.disqualified:
            return await interaction.response.send_message("You have been disqualified", ephemeral=True)
        if [int(interaction.user.id),self.round] in self.usersinround:
            return await interaction.response.send_message("You have already joined the boss", ephemeral=True)
        if self.round != 0 and interaction.user.id not in self.users:
            return await interaction.response.send_message(
                "It is too late to join the boss, or you have died", ephemeral=True
            )
        if interaction.user.id in self.users:
            return await interaction.response.send_message(
                "You have already joined the boss", ephemeral=True
            )
        self.users.append(interaction.user.id)
        await interaction.response.send_message(
            "You have joined the Boss Battle!", ephemeral=True
        )
        await log_action(
            f"{interaction.user} has joined the `{self.bossball}` Boss Battle.",
            self.bot,
        )

    def test(self, interaction: discord.Interaction):
        if [int(interaction.user.id),self.round] in self.usersinround:
            return ("You have already joined the boss")
        if self.round != 0 and interaction.user.id not in self.users:
            return ("It is too late to join the boss, or you have died")
        if interaction.user.id in self.users:
            return ("You have already joined the boss")
        self.users.append(interaction.user.id)
        return ("You have joined the Boss Battle!")


