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
from ballsdex.packages.battle.cog import SPECIALBUFFS, checkpermit
from ballsdex.packages.cashsystem.cog import notallowed
from ballsdex.core.utils.transformers import BallInstanceTransform, SpecialEnabledTransform
from ballsdex.core.utils.transformers import BallEnabledTransform
from ballsdex.core.utils.transformers import SpecialTransform, BallTransform
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.bot import BallsDexBot

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

if settings.bot_name == "dragonballdex":
    dropname = "Zeni Drop"
else:
    dropname = "Credits Drop"


#Change this if you want to a different channel for boss logs
#e.g.
#LOGCHANNEL = 1234567890987654321

async def log_action(serverid, message: str, bot: BallsDexBot, console_log: bool = False):
    if serverid == 1209469444196409404: #rldex server
        LOGCHANNEL = 1321918255274921994 #rldex server boss logs
    else:
        LOGCHANNEL = 1321913349125967896 #dbdex server boss logs
    if LOGCHANNEL:
        channel = bot.get_channel(LOGCHANNEL)
        if not channel:
            log.warning(f"Channel {LOGCHANNEL} not found")
            return
        if not isinstance(channel, discord.TextChannel):
            log.warning(f"Channel {channel.name} is not a text channel")  # type: ignore
            return
        await channel.send(message)
    if console_log:
        log.info(message)

class JoinButton(View):
    def __init__(self, boss_cog):
        super().__init__(timeout=900) #change this if you want
        self.boss_cog = boss_cog
        self.join_button = Button(label="Join Boss Fight!", style=discord.ButtonStyle.primary, custom_id="join_boss")
        self.join_button.callback = self.button_callback
        self.add_item(self.join_button)
    async def button_callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not self.boss_cog.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if int(user_id) in self.boss_cog.disqualified:
            return await interaction.followup.send("You have been disqualified", ephemeral=True)
        if [int(user_id),self.boss_cog.round] in self.boss_cog.usersinround:
            return await interaction.followup.send("You have already joined the boss", ephemeral=True)
        if self.boss_cog.round != 0 and user_id not in self.boss_cog.users:
            return await interaction.followup.send(
                "It is too late to join the boss, or you have died", ephemeral=True
            )
        if user_id in self.boss_cog.users:
            return await interaction.followup.send(
                "You have already joined the boss", ephemeral=True
            )
        
        has_permit = await checkpermit(self.boss_cog, user_id, None)
        if has_permit:
            users_permit = self.boss_cog.permit_users[user_id]
            users_buff = users_permit.attack_bonus
            buff_multiplier = users_buff/100 + 1
        else:
            buff_multiplier = 1
        self.boss_cog.buffs[user_id] = buff_multiplier
        self.boss_cog.users.append(user_id)
        
        await interaction.followup.send(
            "You have joined the Boss Battle!", ephemeral=True
        )
        await log_action(
            self.boss_cog.serverid,
            f"{interaction.user} has joined the {self.boss_cog.bossball} Boss Battle.",
            self.boss_cog.bot,
        )

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
        self.permit_users = {}
        self.buffs = {}
        self.currentvalue = ("")
        self.bossHP = 0
        self.picking = False
        self.round = 0
        self.attack = False
        self.bossattack = 0
        self.bossball = None
        self.bosswildd = []
        self.bosswilda = []
        self.disqualified = []
        self.lasthitter = 0
        self.serverid = 0

    bossadmin = app_commands.Group(name="admin", description="admin commands for boss")

    @bossadmin.command(name="start")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def start(
        self,
        interaction: discord.Interaction,
        countryball: BallTransform,
        hp_amount: int,
        start_image: discord.Attachment | None = None,
        defend_image: discord.Attachment | None = None,
        attack_image: discord.Attachment | None = None):
        """
        Start the boss
        """
        ball = countryball
        if self.boss_enabled == True:
            return await interaction.response.send_message(f"There is already an ongoing boss battle", ephemeral=True)
        if ball.enabled == False:
            disabledperm = False
            for i in settings.root_role_ids:
                if interaction.guild.get_role(i) in interaction.user.roles:
                    disabledperm = True
            if disabledperm == False:
                return await interaction.response.send_message(f"You do not have permission to boss start this {settings.collectible_name}", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        self.serverid = interaction.guild.id
        self.bossHP = hp_amount
        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        if start_image == None:
            extension = ball.collection_card.split(".")[-1]
            file_location = "./admin_panel/media/" + ball.collection_card
            file_name = f"nt_{generate_random_name()}.{extension}"
            file=discord.File(file_location, filename=file_name)
        else:
            file = await start_image.to_file()

        # Create join button view with updated timeout
        view = JoinButton(self)
        
        await interaction.followup.send(
            f"Boss successfully started", ephemeral=True
        )
        message = await interaction.channel.send((f"# The boss battle has begun! {self.bot.get_emoji(ball.emoji_id)}\n-# HP: {self.bossHP} Credits: nobodyboy (Card Art)"),file=file,view=view)
        view.message = message
        if ball != None:
            self.boss_enabled = True
            self.bossball = ball
            if defend_image == None:
                self.bosswildd.append(None)
                self.bosswildd.append(1)
            else:
                self.bosswildd.append(defend_image)
                self.bosswildd.append(2)
            if attack_image == None:
                self.bosswilda.append(None)
                self.bosswilda.append(1)
            else:
                self.bosswilda.append(attack_image)
                self.bosswilda.append(2)

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
        await interaction.response.defer(ephemeral=True, thinking=True)
        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = self.bossball.wild_card.split(".")[-1]
        file_location = "./admin_panel/media/" + self.bossball.wild_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.followup.send(
            f"Round successfully started", ephemeral = True
        )
        if self.bosswilda[1] == 2: #if custom image
            file = await self.bosswilda[0].to_file()
        else:
            file = discord.File(file_location, filename=file_name)
        await interaction.channel.send(
            (f"Round {self.round}\n# {self.bossball.country} is preparing to attack! {self.bot.get_emoji(self.bossball.emoji_id)}"),file=file
        )
        await interaction.channel.send(f"> Use `/boss select` to select your defending {settings.collectible_name}.\n> Your selected {settings.collectible_name}'s HP will be used to defend.")
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = self.bossball.wild_card.split(".")[-1]
        file_location = "./admin_panel/media/" + self.bossball.wild_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.followup.send(
            f"Round successfully started", ephemeral=True
        )
        if self.bosswildd[1] == 2: #if custom image
            file = await self.bosswildd[0].to_file()
        else:
            file = discord.File(file_location, filename=file_name)
        await interaction.channel.send(
            (f"Round {self.round}\n# {self.bossball.country} is preparing to defend! {self.bot.get_emoji(self.bossball.emoji_id)}"),file=file
        )
        await interaction.channel.send(f"> Use `/boss select` to select your attacking {settings.collectible_name}.\n> Your selected {settings.collectible_name}'s ATK will be used to attack.")
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        self.picking = False
        with open("roundstats.txt", "w") as file:
            file.write(f"{self.currentvalue}")
        await interaction.followup.send(
            f"Round successfully ended", ephemeral=True
        )
        if not self.attack:
            if int(self.bossHP) <= 0:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThere is 0 HP remaining on the boss, the boss has been defeated!",
                )
            else:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThere is {self.bossHP} HP remaining on the boss",
                )
        else:
            snapshotusers = self.users.copy()
            for user in snapshotusers:
                user_id = user
                user = await self.bot.fetch_user(int(user))
                if str(user) not in self.currentvalue:
                    self.currentvalue += (str(user) + " has not selected on time and died!\n")
                    self.users.remove(user_id)
            with open("roundstats.txt","w") as file:
                file.write(f"{self.currentvalue}")
            if len(self.users) == 0:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has dealt {self.bossattack} damage!\nThe boss has won!",
                )
            else:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has dealt {self.bossattack} damage!\n",
                )
        with open("roundstats.txt", "rb") as file:
            await interaction.channel.send(file=discord.File(file,"roundstats.txt"))
        self.currentvalue = ("")

    @bossadmin.command(name="stats")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def stats(self, interaction: discord.Interaction):
        """
        See current stats of the boss
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        with open("stats.txt","w") as file:
            file.write(f"Boss:{self.bossball}\nCurrentValue:\n\n{self.currentvalue}\nUsers:{self.users}\nDisqualifiedUsers:{self.disqualified}\nUsersDamage:{self.usersdamage}\nBalls:{self.balls}\nUsersInRound:{self.usersinround}")
        with open("stats.txt","rb") as file:
            return await interaction.followup.send(file=discord.File(file,"stats.txt"), ephemeral=True)

    @bossadmin.command(name="disqualify")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def disqualify(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        user_id : str | None = None,
        undisqualify : bool | None = False,
        ):
        """
        Disqualify a member from the boss
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        if (user and user_id) or (not user and not user_id):
            await interaction.followup.send(
                "You must provide either `user` or `user_id`.", ephemeral=True
            )
            return

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))  # type: ignore
            except ValueError:
                await interaction.followup.send(
                    "The user ID you gave is not valid.", ephemeral=True
                )
                return
            except discord.NotFound:
                await interaction.followup.send(
                    "The given user ID could not be found.", ephemeral=True
                )
                return
        else:
            user_id = user.id
        if int(user_id) in self.disqualified:
            if undisqualify == True:
                self.disqualified.remove(int(user_id))
                await interaction.followup.send(
                    f"{user} has been removed from disqualification.\nUse `/boss admin hackjoin` to join the user back.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"{user} has already been disqualified.\nSet `undisqualify` to `True` to remove a user from disqualification.", ephemeral=True
                )
        elif undisqualify == True:
            await interaction.followup.send(
                f"{user} has **not** been disqualified yet.", ephemeral=True
            )
        elif self.boss_enabled != True:
            self.disqualified.append(int(user_id))
            await interaction.followup.send(
                f"{user} will be disqualified from the next fight.", ephemeral=True
            )
        elif int(user_id) not in self.users:
            self.disqualified.append(int(user_id))
            await interaction.followup.send(
                f"{user} has been disqualified successfully.", ephemeral=True
            )
            return
        else:
            self.users.remove(int(user_id))
            self.disqualified.append(int(user_id))
            await interaction.followup.send(
                f"{user} has been disqualified successfully.", ephemeral=True
            )
            return

    
    @app_commands.command()
    async def select(
        self,
        interaction: discord.Interaction,
        countryball: BallInstanceTransform,
        special: SpecialEnabledTransform | None = None,
    ):
        """
        Select countryball to use against the boss.
        
        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to select
        special: Special
            Filter the results of autocompletion to a special event. Ignored afterwards.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        ball = countryball
        if [int(interaction.user.id),self.round] in self.usersinround:
            return await interaction.followup.send(
                f"You have already selected a {settings.collectible_name}", ephemeral=True
            )
        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if not self.picking:
            return await interaction.followup.send(f"It is not yet time to select an {settings.collectible_name}", ephemeral=True)
        if interaction.user.id not in self.users:
            return await interaction.followup.send(
                "You did not join, or you're dead/disqualified.", ephemeral=True
            )
        if not (await countryball.ball).tradeable:
            await interaction.followup.send(
                f"You cannot use this {settings.collectible_name}.", ephemeral=True
            )
            return
        countryballname = f"{await countryball.ball}"
        if any(substring in countryballname.lower() for substring in [x.lower() for x in notallowed]):
            return await interaction.followup.send(f"You cannot use this")
        if ball in self.balls:
            return await interaction.followup.send(
                f"You cannot select the same {settings.collectible_name} twice", ephemeral=True
            )
        if ball == None:
            return
        self.balls.append(ball)
        self.usersinround.append([int(interaction.user.id),self.round])
        users_buff = self.buffs[interaction.user.id]
        bufftext1 = ""
        bufftext2 = ""
        countryballspecial = await countryball.special
        countryballspecial = f"{countryballspecial}"
        if settings.bot_name == "dragonballdex":
            maxvalue = 240000
            bot_key = "dragonballdex"
        else:
            maxvalue = 24000
            bot_key = "rocketleaguedex"
        buff = SPECIALBUFFS.get(countryballspecial, {}).get(bot_key, 0)
        if users_buff != 1:
            bufftext1 = "**"
            bufftext2 = "** ⚡"
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

        # Default base message
        originaldescription = ball.description(short=True, include_emoji=True, bot=self.bot)
        originalballattack = ballattack
        originalballhealth = ballhealth
        messageforuser = (
            f"{originaldescription} "
            f"has been selected for this round, with {originalballattack} ATK and {originalballhealth} HP"
        )
        
        if buff > 0:
            buff = int(buff*users_buff)
            ballattack += buff
            ballhealth += buff
            messageforuser = (
                f"{originaldescription} "
                f"has been selected for this round, with {originalballattack}{bufftext1}+{buff}{bufftext2} ATK and {originalballhealth}{bufftext1}+{buff}{bufftext2} HP"
            )

            
        if not self.attack:
            self.bossHP -= ballattack
            self.usersdamage.append([int(interaction.user.id),ballattack,ball.description(short=True, include_emoji=True, bot=self.bot)])
            self.currentvalue += (str(interaction.user)+"'s "+str(ball.description(short=True, bot=self.bot))+" has dealt "+(str(ballattack))+" damage!\n")
            self.lasthitter = int(interaction.user.id)
        else:
            if self.bossattack >= ballhealth:
                self.users.remove(interaction.user.id)
                self.currentvalue += (str(interaction.user)+"'s "+str(ball.description(short=True, bot=self.bot))+" had "+(str(ballhealth))+"HP and died!\n")
            else:
                self.currentvalue += (str(interaction.user)+"'s "+str(ball.description(short=True, bot=self.bot)) + " had " + (str(ballhealth)) + "HP and survived!\n")

        await interaction.followup.send(
            messageforuser, ephemeral=True
        )
        await log_action(
            self.serverid,
            f"-# Round {self.round}\n{interaction.user}'s {messageforuser}\n-# -------",
            self.bot,
        )

    @app_commands.command()
    async def ongoing(self, interaction: discord.Interaction):
        """
        Show your damage to the boss in the current fight.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        snapshotdamage = self.usersdamage.copy()
        ongoingvalue = ("")
        ongoingfull = 0
        ongoingdead = False
        for i in range(len(snapshotdamage)):
            if snapshotdamage[i][0] == interaction.user.id:
                ongoingvalue += f"{snapshotdamage[i][2]}: {snapshotdamage[i][1]}\n\n"
                ongoingfull += snapshotdamage[i][1]
        if ongoingfull == 0:
            if interaction.user.id in self.users:
                await interaction.followup.send("You have not dealt any damage.",ephemeral=True)
            elif interaction.user.id in self.disqualified:
                await interaction.followup.send("You have been disqualified.",ephemeral=True)
            else:
                await interaction.followup.send("You have not joined the battle, or you have died.",ephemeral=True)
        else:
            if interaction.user.id in self.users:
                await interaction.followup.send(f"You have dealt {ongoingfull} damage.\n{ongoingvalue}",ephemeral=True)
            elif interaction.user.id in self.disqualified:
                await interaction.followup.send(f"You have dealt {ongoingfull} damage and have been disqualified.\n{ongoingvalue}",ephemeral=True)
            else:
                await interaction.followup.send(f"You have dealt {ongoingfull} damage and you are now dead.\n{ongoingvalue}",ephemeral=True)


    @bossadmin.command(name="ping")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def ping(self, interaction: discord.Interaction, unselected: bool | None = False):
        """
        Ping all the alive players
        """
        snapshotusers = self.users.copy()
        await interaction.response.defer(ephemeral=True, thinking=True)
        if len(snapshotusers) == 0:
            return await interaction.followup.send("There are no users joined/remaining",ephemeral=True)
        pingsmsg = "-#"
        if unselected:
            for userid in snapshotusers:
                if [userid,self.round] not in self.usersinround:
                    pingsmsg = pingsmsg+" <@"+str(userid)+">"
        else:
            for userid in snapshotusers:
                pingsmsg = pingsmsg+" <@"+str(userid)+">"
        if pingsmsg == "-#":
            await interaction.followup.send("All users have selected",ephemeral=True)
        elif len(pingsmsg) < 2000:
            await interaction.followup.send("Ping Successful",ephemeral=True)
            await interaction.channel.send(pingsmsg)
        else:
            await interaction.followup.send("Message too long, exceeds 2000 character limit",ephemeral=True)
            

    @bossadmin.command(name="conclude")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    @app_commands.choices(
        winner=[
            app_commands.Choice(name="Random", value="RNG"),
            app_commands.Choice(name="Most Damage", value="DMG"),
            app_commands.Choice(name="Last Hitter", value="LAST"),
            app_commands.Choice(name="No Winner", value="None"),
        ]
    )
    async def conclude(self, interaction: discord.Interaction, winner: str):
        """
        Finish the boss, conclude the Winner
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.lasthitter not in self.users and winner == "LAST":
            return await interaction.followup.send(
                f"The last hitter is dead or disqualified.", ephemeral=True
            )
        self.picking = False
        self.boss_enabled = False
        test = self.usersdamage
        test2 = []
        total = ("")
        total2 = ("")
        totalnum = []
        for i in range(len(test)):
            if test[i][0] not in test2:
                temp = 0
                tempvalue = test[i][0]
                test2.append(tempvalue)
                for j in range(len(test)):
                    if test[j][0] == tempvalue:
                        temp += test[j][1]
                if test[i][0] in self.users:
                    user = await self.bot.fetch_user(int(tempvalue))
                    total += (f"{user} has dealt a total of " + str(temp) + " damage!\n")
                    totalnum.append([tempvalue, temp])
                else:
                    user = await self.bot.fetch_user(int(tempvalue))
                    total2 += (f"[Dead/Disqualified] {user} has dealt a total of " + str(temp) + " damage!\n")

        bosswinner = 0
        highest = 0
        highestdmgplayer = 0
        currencyawards = {}
        for k in range(len(totalnum)):
            if totalnum[k][1] > highest:
                highest = totalnum[k][1]
                highestdmgplayer = totalnum[k][0]
        if winner == "DMG":
            bosswinner = highestdmgplayer
        elif winner == "LAST":
            bosswinner = self.lasthitter
        elif winner == "RNG":
            if len(totalnum) != 0:
                bosswinner = totalnum[random.randint(0,len(totalnum)-1)][0]
                
        currencyawards = {player[0]: 1 for player in totalnum}

        if bosswinner != 0:
            currencyawards[bosswinner] = 3

        if highestdmgplayer != 0 and highestdmgplayer != bosswinner:
            currencyawards[highestdmgplayer] = 2

        boss_lines = []
        highest_lines = []
        dropstext = ""
        others_exist = False
        
        dropball = [x for x in balls.values() if x.country == dropname][0]
        async def givedrops(n,player_id):
            for i in range(n):
                player, created = await Player.get_or_create(discord_id=player_id)
                instance = await BallInstance.create(
                    ball=dropball,
                    player=player,
                    special=None,
                    attack_bonus=0,
                    health_bonus=0,
                )

        for player, amount in currencyawards.items():
            await givedrops(amount,player)
            if amount == 3:
                boss_lines.append(f"<@{player}> (Winner): 3× {dropname}")
            elif amount == 2:
                highest_lines.append(f"<@{player}> (Highest Damage): 2× {dropname}")
            else:
                others_exist = True

        for line in boss_lines:
            dropstext += f"\n-# - {line}"
        for line in highest_lines:
            dropstext += f"\n-# - {line}"
        if others_exist:
            dropstext += f"\n-# - Other alive players (each): 1× {dropname}"

        if dropstext != "":
            dropstext = f"\nDrop rewards:{dropstext}\n-# Use `/drop open` to open your drops!\n\n-# Use `/upgrade stats` or `/upgrade buffs` to get even stronger!"
        else:
            dropstext = f"-# Use `/upgrade stats` or `/upgrade buffs` to get even stronger!"
                
        if bosswinner == 0:
            await interaction.followup.send(
                f"Boss successfully concluded", ephemeral=True
            )
            await interaction.channel.send(f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has won the Boss Battle!\n\n{dropstext}")
            with open("totalstats.txt", "w") as file:
                file.write(f"{total}{total2}")
            with open("totalstats.txt", "rb") as file:
                await interaction.channel.send(file=discord.File(file, "totalstats.txt"))
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
            self.bosswildd = []
            self.bosswilda = []
            self.disqualified = []
            self.lasthitter = 0
            self.serverid = 0
            self.buffs.clear()
            return
        if winner != "None":
            player, created = await Player.get_or_create(discord_id=bosswinner)
            special = [x for x in specials.values() if x.name == "Boss"][0]
            instance = await BallInstance.create(
                ball=self.bossball,
                player=player,
                special=special,
                attack_bonus=0,
                health_bonus=0,
            )
            await interaction.followup.send(
                f"Boss successfully concluded", ephemeral=True
            )
            await interaction.channel.send(
                f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}\n<@{bosswinner}> has won the Boss Battle!\n\n"
                f"`Boss` `{self.bossball}` {settings.collectible_name} was successfully given.\n\n{dropstext}\n"
            )
            bosswinner_user = await self.bot.fetch_user(int(bosswinner))

            await log_action(
                self.serverid,
                f"`BOSS REWARDS` gave {settings.collectible_name} {self.bossball.country} to {bosswinner_user}."
                f"Special=Boss "
                f"ATK=0 HP=0",
                self.bot,
            )
        else:
            await interaction.followup.send(
                f"Boss successfully concluded", ephemeral=True
            )
            await interaction.channel.send(f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has been defeated!\n\n{dropstext}")
        
        with open("totalstats.txt", "w") as file:
            file.write(f"{total}{total2}")
        with open("totalstats.txt", "rb") as file:
            await interaction.channel.send(file=discord.File(file, "totalstats.txt"))
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
        self.bosswildd = []
        self.bosswilda = []
        self.disqualified = []
        self.lasthitter = 0
        self.serverid = 0
        self.buffs.clear()

    @bossadmin.command(name="hackjoin")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def hackjoin(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        user_id : str | None = None,
        ):
        """
        Join a user to the boss battle.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        if (user and user_id) or (not user and not user_id):
            await interaction.followup.send(
                "You must provide either `user` or `user_id`.", ephemeral=True
            )
            return

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))  # type: ignore
            except ValueError:
                await interaction.followup.send(
                    "The user ID you gave is not valid.", ephemeral=True
                )
                return
            except discord.NotFound:
                await interaction.followup.send(
                    "The given user ID could not be found.", ephemeral=True
                )
                return
        else:
            user_id = user.id

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if [int(user_id), self.round] in self.usersinround:
            return await interaction.followup.send("This user is already in the boss battle.", ephemeral=True)
        if int(user_id) in self.users:
            return await interaction.followup.send(
                "This user is already in the boss battle.", ephemeral=True
            )
        self.users.append(user_id)
        has_permit = await checkpermit(self, user_id, None)
        if has_permit:
            users_permit = self.permit_users[user_id]
            users_buff = users_permit.attack_bonus
            buff_multiplier = users_buff/100 + 1
        else:
            buff_multiplier = 1
        self.buffs[user_id] = buff_multiplier
        if user_id in self.disqualified:
            self.disqualified.remove(user_id)
        await interaction.followup.send(
            f"{user} has been hackjoined into the Boss Battle.", ephemeral=True
        )
        await log_action(
            self.serverid,
            f"{user} has joined the `{self.bossball}` Boss Battle. [hackjoin by {await self.bot.fetch_user(int(interaction.user.id))}]",
            self.bot,
        )


