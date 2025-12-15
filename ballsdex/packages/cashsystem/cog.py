import discord
import logging
import random
import re
import tempfile
import traceback
import asyncio
import math

from ballsdex.packages.countryballs.countryball import BallSpawnView
from datetime import datetime
from discord.utils import get
from discord import app_commands
from discord import Embed
from discord.ext import commands
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q
from tortoise.timezone import now as tortoise_now
from datetime import timedelta

from ballsdex.settings import settings
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.buttons import ConfirmChoiceView
from ballsdex.core.utils.logging import log_action
from ballsdex.settings import settings
from ballsdex.core.models import Player, BallInstance, specials, Trade, balls
from ballsdex.core.bot import BallsDexBot
from ballsdex.core.utils.transformers import (
    BallTransform,
    EconomyTransform,
    RegimeTransform,
    SpecialTransform,
    BallEnabledTransform,
    BallInstanceTransform,
    SpecialEnabledTransform,
)

from typing import TYPE_CHECKING
from collections import Counter

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.zeni")

ZENI_NOTES = [1,2,5,10,20,50,100,200,500] 
currencycards = []


if settings.bot_name == "dragonballdex":
    T1Req = 200 #requirements for upgrading (cost for increasing a stat by 100%
    T1Rarity = 1
    CommonReq = 5
    CommonRarity = 62
    LimitedReq = 500
    currencyname = "Zeni"
    UPGRADECHANNEL = 1448933355575054417
    for i in range(1,10):
        currencycards.append(495+i) #495 main bot 195 test bot
else:
    T1Req = 80 #requirements for upgrading (cost for increasing a stat by 20%)
    T1Rarity = 1
    CommonReq = 5
    CommonRarity = 233
    LimitedReq = 200
    currencyname = "Credits"
    UPGRADECHANNEL = 1448933419886186608
    for i in ZENI_NOTES:
        if i == 1:
            currencycardname = f"1 Credit"
        else:
            currencycardname = f"{i} Credits"
        currencycard = [x for x in balls.values() if x.country==currencycardname][0]
        currencycards.append(currencycard.id)

async def upgrade_log_action(message: str, bot: BallsDexBot, console_log: bool = False): #to log every upgrade someone does
    if UPGRADECHANNEL:
        channel = bot.get_channel(UPGRADECHANNEL)
        if not channel:
            log.warning(f"Channel {UPGRADECHANNEL} not found")
            return
        if not isinstance(channel, discord.TextChannel):
            log.warning(f"Channel {channel.name} is not a text channel")  # type: ignore
            return
        await channel.send(message)
    if console_log:
        log.info(message)
gradient = (CommonReq-T1Req)/(CommonRarity-T1Rarity)
notallowed = ["zeni","credit","relic","dragon ball (","drop"]

class cashsystem(commands.Cog):
    """
    Zeni commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.permit_users = {}

    currencycommands = app_commands.Group(
        name=currencyname.lower(), description=f'{currencyname} commands'
    )

    upgradecommands = app_commands.Group(
        name="upgrade", description=f'Upgrade commands'
    )

    def get_zeni(self,zeninote):
        zeniposition = ZENI_NOTES.index(zeninote)
        currency = currencycards[zeniposition]
        return [x for x in balls.values() if x.id==currency][0]

    def get_permit(self):
        permitname = f"{currencyname} Permit"
        permitball = [x for x in balls.values() if x.country==permitname][0]
        return permitball

    async def zeni_balance(self, user, returnballs: bool):
        zenitable = []
        totalzeni = 0
        balllist = []
        for zeninumber in ZENI_NOTES:
            filters = {}
            filters["ball"] = self.get_zeni(zeninumber)
            if user is not None:
                filters["player__discord_id"] = user.id
            balls = await BallInstance.filter(**filters).count()
            if returnballs:
                balllist.append(await BallInstance.filter(**filters).prefetch_related("ball"))
            zenirow = (zeninumber,balls,zeninumber*balls)
            zenitable.append(zenirow)
            totalzeni += zeninumber*balls

        if returnballs:
            return zenitable, totalzeni, balllist
        else:
            return zenitable, totalzeni

    def map_rarity_to_req(self, rarity):
        exponent = 2.5
        norm = (rarity - T1Rarity) / (CommonRarity - T1Rarity)
        return CommonReq + (T1Req - CommonReq) * (1 - norm) ** exponent

    def exponential_pricing(self, x):
        start_value = 50 #initial cost
        growth_rate = 0.025
        return math.ceil(start_value * (2 ** ((x - 1) * growth_rate)))

    def optimal_payment(self, price: int, balance_rows):
        wallet = {zeni: count for (zeni, count, _) in balance_rows}
        ZENI = sorted(ZENI_NOTES)  # ascending
        ZENI_DESC = list(reversed(ZENI))  # descending (for priority)

        max_pay = sum(d * wallet[d] for d in ZENI)
        INF = float("inf")

        dp = [INF] * (max_pay + 1)
        used_map = [{} for _ in range(max_pay + 1)]
        dp[0] = 0

        def better_high_priority(a, b):
            """Return True if usage a is better than b with high-note priority"""
            for d in ZENI_DESC:
                if a.get(d, 0) != b.get(d, 0):
                    return a.get(d, 0) > b.get(d, 0)
            return False

        for d in ZENI:
            for _ in range(wallet[d]):
                for v in range(max_pay, d - 1, -1):
                    if dp[v - d] != INF:
                        candidate_sum = dp[v - d] + d
                        candidate_used = used_map[v - d].copy()
                        candidate_used[d] = candidate_used.get(d, 0) + 1

                        if (
                            candidate_sum < dp[v] or
                            (
                                candidate_sum == dp[v] and
                                better_high_priority(candidate_used, used_map[v])
                            )
                        ):
                            dp[v] = candidate_sum
                            used_map[v] = candidate_used

        total_paid = None
        used = None

        for v in range(price, max_pay + 1):
            if dp[v] != INF:
                total_paid = v
                used = used_map[v]
                break

        if total_paid is None:
            return None, None, None, None

        change = total_paid - price

        # Change breakdown (unlimited supply, greedy high-first)
        change_breakdown = {}
        rem = change
        for d in ZENI_DESC:
            c = rem // d
            if c:
                change_breakdown[d] = c
                rem -= d * c

        final_used = {d: used.get(d, 0) for d in ZENI}
        return final_used, total_paid, change, change_breakdown

    async def pay(self, interaction:discord.Interaction, payment:int):
        if payment == 1 and currencyname == "Credits":
            amountcurrency = "Credit"
        else:
            amountcurrency = currencyname
        zenibalance = await self.zeni_balance(interaction.user,True)
        zenitable = zenibalance[0]
        totalzeni = zenibalance[1]
        if totalzeni < payment:
            if totalzeni == 1 and currencyname == "Credits":
                totalcurrency = "Credit"
            else:
                totalcurrency = currencyname
            await interaction.followup.send(f"You cannot afford this! You only have {totalzeni} {totalcurrency}\nYou can get {currencyname} by using the `/daily` command.", ephemeral=True)
            return False
        
        balllist = zenibalance[2]

        process = self.optimal_payment(payment,zenitable)
        paytext = f"{payment} {amountcurrency} payment complete!\n"

        zenilisttaken = process[0]

        zenitaken = process[1]
        if zenitaken == 1 and currencyname == "Credits":
            paidcurrency = "Credit"
        else:
            paidcurrency = currencyname

        changegiven = process[2]
        if changegiven == 1 and currencyname == "Credits":
            changecurrency = "Credit"
        else:
            changecurrency = currencyname

        changelistgiven = process[3]
        
        paytext += f"Paid: {zenitaken} {paidcurrency}\nNotes taken:\n"
        valuecounter = 0
        balllisttopay = []
        for value, amount in zenilisttaken.items(): # value: 1,2,5,10,20,50 etc #amount: how much you have of the value
            if amount > 0:
                for i in range(amount):
                    balltopay = balllist[valuecounter][i]
                    if await balltopay.is_locked() == True:
                        await interaction.followup.send(f"You have an ongoing trade containing {currencyname}. Finish/cancel the trade and try again.\nIf you do not currently have an ongoing trade, wait 30 minutes.", ephemeral=True)
                        if len(balllisttopay) > 0:
                            for b in balllisttopay:
                                await b.unlock()
                        return False
                    balllisttopay.append(balltopay)
                    await balltopay.lock_for_trade()
                if value == 1 and currencyname == "Credits":
                    paidcurrency = "Credit"
                else:
                    paidcurrency = currencyname
                paytext += f"- {amount}× {value} {paidcurrency}\n"
            valuecounter += 1

        for b in balllisttopay:
            await b.delete()

        if changegiven >0:
            player, _ = await Player.get_or_create(discord_id=interaction.user.id)
            paytext += f"\nChange: {changegiven} {changecurrency}\nChange breakdown:\n"
            for value, amount in changelistgiven.items():
                if amount > 0:
                    for i in range(amount):
                        changetogive = self.get_zeni(value)
                        instance = await BallInstance.create(
                            ball=changetogive,
                            player=player,
                            special=None,
                            attack_bonus=0,
                            health_bonus=0,
                        )
                    if value == 1 and currencyname == "Credits":
                        changecurrency = "Credit"
                    else:
                        changecurrency = currencyname
                    paytext += f"- {amount}× {value} {changecurrency}\n"
        
        await interaction.followup.send(paytext, ephemeral=True)
        return True

    async def check_permit(self, interaction):
        user_id = interaction.user.id
        pfilters = {}
        permitball = self.get_permit()
        pfilters["ball"] = permitball
        pfilters["player__discord_id"] = user_id
        permitcheck = await BallInstance.filter(**pfilters).count()
        permitlist = await BallInstance.filter(**pfilters).prefetch_related("ball")
        if permitcheck == 0:
            view = ConfirmChoiceView(
                interaction,
                accept_message=f"Confirmed, granting {currencyname} Permit...",
                cancel_message="Request cancelled.",
            )
            await interaction.followup.send(
                f"By using the upgrade commands you agree that ALL purchases are NON-REFUNDABLE.\nWould you like to continue? (You will recieve a permit that allows you to spend {currencyname} on upgrades.)\n\n-# You can get {currencyname} by using the `/daily` command.",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if view.value:
                if user_id in self.permit_users: #incase someone uses the command multiple times
                    await interaction.followup.send(f"Error. You already have {currencyname} Permit.",ephemeral=True)
                    return False
                player, _ = await Player.get_or_create(discord_id=user_id)
                permitinstance = await BallInstance.create(
                    ball=permitball,
                    player=player,
                    special=None,
                    attack_bonus=0,
                    health_bonus=0,
                    server_id=1238814628327325716, #as a mark that the permit was given by this command, not spawned/given
                    spawned_time=tortoise_now() - timedelta(hours=1), #as a mark that the permit was given by this command, not spawned/given
                )
                self.permit_users[user_id] = permitinstance
                await interaction.followup.send(
                    f"{currencyname} Permit successfully given.\nUse this command again to continue upgrading.",
                    ephemeral=True,
                )
                await log_action(
                    f"{interaction.user}({user_id}): Granted {permitinstance}\n",
                    interaction.client,
                )
            return False
        
        #check your permits if you have 1 or more
        foundpermit = False
        valid_permit = None
        deleted_permits = []
        for pb in permitlist:
            if pb.server_id != 1238814628327325716: #if it was given by admin or caught force caught
                deleted_permits.append(pb.description(bot=self.bot))
                pb.deleted = True #soft delete
                await pb.save()
            else:
                foundpermit = True
                valid_permit = pb

        if deleted_permits:
            logtext = (
                f"{interaction.user}({user_id}): Soft deleted invalid permit(s):\n" +
                "\n".join(f"- {d}" for d in deleted_permits)
            )
            await log_action(logtext, interaction.client)

        #recurse if no valid permits remain
        if not foundpermit:
            return await self.check_permit(interaction)

        #check again how many valid permits remain
        permitcheck2 = await BallInstance.filter(**pfilters).count()
        if permitcheck2 > 1:
            valid_permits = []
            permitlist2 = await BallInstance.filter(**pfilters).prefetch_related("ball")
            for pb in permitlist2:
                valid_permits.append(pb.description(bot=self.bot))
            logtext2 = (
                f"⚠️ {interaction.user}({user_id}): ULTRA RARE ERROR (multi valid permits) ⚠️\n" +
                "\n".join(f"- {d}" for d in valid_permits)
            )
            await log_action(logtext2, interaction.client)
            await interaction.followup.send("You have found an ultra rare error!\nDm moofficial0 for a fix.") #very rare
            return False

        #if exactly one valid permit
        self.permit_users[user_id] = valid_permit
        return True


    @currencycommands.command(name="count",description=f"Count how much {currencyname} you own.")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def count(
        self,
        interaction: discord.Interaction,
        ephemeral: bool = False,
    ):
        """
        Parameters
        ----------
        ephemeral: bool
            Whether or not to send the command ephemerally.
        """
        if interaction.response.is_done():
            return
        
        assert interaction.guild

        await interaction.response.defer(ephemeral=ephemeral, thinking=True)

        zenibalance = await self.zeni_balance(interaction.user,False)
        zenitable = zenibalance[0]
        totalzeni = zenibalance[1]
        
        max_field1 = (8 if settings.bot_name == "dragonballdex" else 11)
        max_field2 = max(len(str(field2)) for field1,field2,field3 in zenitable) + 4
        max_field3 = max(len(str(field3)) for field1,field2,field3 in zenitable) + 4
        table = f"**Total {currencyname}**: {totalzeni}\n\n**{currencyname} Breakdown**:```\n"
        table += f"{'Name':<{max_field1}} | {'Count':<{max_field2}} | {f'Subtotal':<{max_field3}}\n"
        table += f"{'-'*max_field1}-+-{'-'*max_field2}-+-{'-'*max_field3}\n"
        use_credits = (settings.bot_name != "dragonballdex")
        for field1, field2, field3 in zenitable:
            currencyname1 = "Credit" if use_credits and field1 == 1 else currencyname
            field1zeni = f"{field1} {currencyname1}"
            table += f"{field1zeni:<{max_field1}} | {field2:<{max_field2}} | {field3:<{max_field3}}\n"
        table += f"```\n-# You can get {currencyname} by using the `/daily` command."
        embed = discord.Embed(
            title=f"Total {currencyname} count",
            description=table,
            color=discord.Color.blurple(),
        )
        embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )
        await interaction.followup.send(embed=embed)

    
    @upgradecommands.command(name="stats",description=f"Upgrade or downgrade {settings.collectible_name} stats.")
    @app_commands.checks.cooldown(1, 100, key=lambda i: i.user.id)
    async def stats(
        self,
        interaction: discord.Interaction,
        countryball: BallInstanceTransform,
        new_attack_bonus: app_commands.Range[int, -1*settings.max_attack_bonus, settings.max_attack_bonus] | None = None,
        new_health_bonus: app_commands.Range[int, -1*settings.max_health_bonus, settings.max_health_bonus] | None = None,
    ):

        if interaction.response.is_done():
            return
        
        assert interaction.guild

        await interaction.response.defer(ephemeral=True, thinking=True)

        user_id = interaction.user.id
        if user_id not in self.permit_users:
            if not await self.check_permit(interaction):
                return

        permitball = self.permit_users[user_id]

        # Incase it got hard deleted
        try:
            permitball = await BallInstance.get(id=permitball.id)
        except DoesNotExist:
            # Remove bad cache entry
            self.permit_users.pop(user_id, None)
            await log_action(
                f"{user_id}'s {permitball}: DELETED ERROR\nPopped from `self.permit_users`, retrying `self.check_permit`\n",
                interaction.client,
            )

            # Try verifying again
            if not await self.check_permit(interaction):
                return

            permitball = self.permit_users[user_id]

        # Incase it got soft deleted
        if permitball.deleted: #this will likely never be true, only used incase DoesNotExist did not trigger for soft deleted balls for any reason
            self.permit_users.pop(user_id, None)
            await log_action(
                f"{user_id}'s {permitball}: DELETED ERROR\nPopped from `self.permit_users`, retrying `self.check_permit`\n",
                interaction.client,
            )

            if not await self.check_permit(interaction):
                return

            permitball = self.permit_users[user_id]

        # Incase it got transferred by an admin
        user_player, _ = await Player.get_or_create(discord_id=user_id)
        
        if permitball.player_id != user_player.id:
            self.permit_users.pop(user_id, None)
            await log_action(
                f"{user_id}'s {permitball}: TRANSFERRED ERROR\nPopped from `self.permit_users`, retrying `self.check_permit`\n",
                interaction.client,
            )

            if not await self.check_permit(interaction):
                return

            permitball = self.permit_users[user_id]
        currentupgradecount = permitball.health_bonus
                
        countryballname = f"{await countryball.ball}"

        if any(substring in countryballname.lower() for substring in [x.lower() for x in notallowed]):
            return await interaction.followup.send(f"You cannot upgrade this")
                
        if new_health_bonus == None and new_attack_bonus == None:
            return await interaction.followup.send(f"Must provide `new_attack_bonus` and/or `new_health_bonus`")
        
        if await countryball.is_locked() == True:
            return await interaction.followup.send(
                f"This {settings.collectible_name} is currently locked for a trade. "
                "Please try again later.",
                ephemeral=True,
            )

        if (await countryball.ball).enabled:
            fullcost = self.map_rarity_to_req((await countryball.ball).rarity)
        else:
            fullcost = LimitedReq
        statcost = fullcost/settings.max_health_bonus #max health bonus and max attack bonus are equal to each other, true for both dexes
        health_cost = 0
        attack_cost = 0

        old_attack = countryball.attack_bonus
        old_health = countryball.health_bonus

        updates = {}
        attackwarning = ""
        healthwarning = ""
        if new_health_bonus is not None:
            new_health = new_health_bonus
            updates['health_bonus'] = new_health
            if new_health == old_health:
                return await interaction.followup.send(f"`new_health_bonus` cannot be the same as original health bonus")
            health_change = abs(new_health - old_health)
            if new_health - old_health < 0:
                healthwarning = "\n⚠️ WARNING: The new health bonus is a **downgrade**. ⚠️"
            health_cost = int(health_change*statcost)
            if health_cost == 0:
                health_cost = 1
        else:
            new_health = old_health
        if new_attack_bonus is not None:
            new_attack = new_attack_bonus
            updates['attack_bonus'] = new_attack
            if new_attack == old_attack:
                return await interaction.followup.send(f"`new_attack_bonus` cannot be the same as original attack bonus")
            attack_change = abs(new_attack - old_attack)
            if new_attack - old_attack < 0:
                attackwarning = "\n⚠️ WARNING: The new attack bonus is a **downgrade**. ⚠️"
            attack_cost = int(attack_change*statcost)
            if attack_cost == 0:
                attack_cost = 1
        else:
            new_attack = old_attack


        old_atk_sign = "+" if old_attack >= 0 else ""
        old_hp_sign  = "+" if old_health >= 0 else ""   
        new_atk_sign = "+" if new_attack >= 0 else ""
        new_hp_sign  = "+" if new_health >= 0 else ""

        upgradetext = (
            f"{countryball} "
            f"(`{old_atk_sign}{old_attack}ATK`,`{old_hp_sign}{old_health}HP`) "
            f"----> "
            f"(`{new_atk_sign}{new_attack}ATK`,`{new_hp_sign}{new_health}HP`)"
        )
                
        await countryball.lock_for_trade()
        total_cost = (health_cost+attack_cost)
        
        view = ConfirmChoiceView(
            interaction,
            accept_message=f"Confirmed, attempting to change {countryball} stats...",
            cancel_message="Request cancelled.",
        )
        if total_cost == 1 and currencyname == "Credits":
            changecurrency = "Credit"
        else:
            changecurrency = currencyname
        await interaction.followup.send(
            f"You are planning to change:\n{upgradetext}{attackwarning}{healthwarning}\n\nThis will cost {total_cost} {changecurrency}\n-# You can get {currencyname} by using the `/daily` command.",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        
        await countryball.unlock() #unlocks after either ConfirmChoiceView timeouts, accepted or cancelled.
        
        if view.value:
            if await self.pay(interaction, total_cost):
                permitball.health_bonus += 1
                await permitball.save()
                resultupgradetext = f"{settings.collectible_name.capitalize()} successfully changed!\n{upgradetext}\n-# You have completed a total of **{currentupgradecount+1}** {settings.collectible_name} stat changes!"
                
                for key, value in updates.items():
                    setattr(countryball, key, value)
                await countryball.save()
                await interaction.followup.send(
                    resultupgradetext,
                    ephemeral=True,
                )
                await upgrade_log_action(
                    f"{interaction.user}({user_id}): Upgrade {upgradetext}\n{total_cost} {changecurrency}",
                    self.bot,
                )
            
    async def buffupdate(self, interaction: discord.Interaction, permitball):
        await interaction.response.defer(thinking=True,ephemeral=True)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.primary, emoji="⏫", label="Upgrade", disabled=True))
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="❓", label="Explain this to me!", disabled=True))
        await interaction.message.edit(view=view)
        currentbuff = permitball.attack_bonus
        currentpricing = int(self.exponential_pricing(currentbuff+1))
        if await self.pay(interaction, currentpricing):
            currentbuff = currentbuff+1 #renew
            pricing = int(self.exponential_pricing(currentbuff+1))
            permitball.attack_bonus = currentbuff
            await permitball.save()
            embed = discord.Embed(
                title=f"✨🌌 Special Buffs Upgrading 🌌✨",
                description=f"Upgrade Special Buffs to deal more in battles and boss battles!\nWorks on all specials."
            )
            embed.color=discord.Color.from_rgb(255,239,71)
            embed.set_author(name=interaction.user, icon_url=interaction.user.avatar.url)
            embed.add_field(
                name="CURRENT BUFF LEVEL:",
                value=f" **+{currentbuff}%**",
                inline=False
            )
            embed.add_field(
                name="NEXT BUFF LEVEL:",
                value=f" **+{currentbuff+1}%**\n\u200b",
                inline=False
            )

            embed.add_field(
                name="💰 Upgrade Cost:",
                value=f"**{pricing}** {currencyname}\n-# You can get {currencyname} by using the `/daily` command.\n\u200b",
                inline=False
            )
            
            embed.set_footer(
                text=f"Your special buffs are currently **boosted** an extra {currentbuff}% for you!⚡\n💡 Use `/special_buffs` to check your buffs for each special."
            )

            await upgrade_log_action(
                f"{interaction.user}({interaction.user.id}) Upgrade SPECIAL BUFFS from `+{currentbuff-1}%` to `+{currentbuff}%`\n{currentpricing} {currencyname}", #-1 so it doesnt use new values
                self.bot,
            ) 

            
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.InteractionResponded:
                pass
            await interaction.message.edit(embed=embed)
            await asyncio.sleep(5)
            
            new_upgrade_button = discord.ui.Button(
                style=discord.ButtonStyle.primary, emoji="⏫", label="Upgrade"
            )
            new_explain_button = discord.ui.Button(
                style=discord.ButtonStyle.secondary, emoji="❓", label="Explain this to me!"
            )
            original_user = interaction.user
            async def new_callback(i: discord.Interaction):
                if i.user != original_user:
                    await i.response.send_message("This button isn't for you!", ephemeral=True)
                    return
                await self.buffupdate(i,permitball)

            async def new_explain_callback(button_interaction: discord.Interaction):
                if button_interaction.user != original_user:
                    await button_interaction.response.send_message(
                        "`/upgrade explain` → `explain:/upgrade buffs`", ephemeral=True
                    )
                    return
                
                new_explain_button.disabled = True
                new_upgrade_button.disabled = True
                await button_interaction.response.edit_message(view=view)
                
                await self.explain_logic(
                    button_interaction,
                    "BUFF"
                )
                await asyncio.sleep(5)
                
                new_explain_button.disabled = False
                new_upgrade_button.disabled = False
                await button_interaction.followup.edit_message(message_id=button_interaction.message.id, view=view)

            new_upgrade_button.callback = new_callback
            new_explain_button.callback = new_explain_callback

            view = discord.ui.View(timeout=60)
            view.add_item(new_upgrade_button)
            view.add_item(new_explain_button)
            await interaction.message.edit(view=view)

        
    @upgradecommands.command(name="buffs",description=f"Upgrade or downgrade buffs of all specials.")
    @app_commands.checks.cooldown(1, 100, key=lambda i: i.user.id)
    async def buffs(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.response.is_done():
            return
        
        assert interaction.guild

        await interaction.response.defer(thinking=True,ephemeral=True)

        user_id = interaction.user.id
        if user_id not in self.permit_users:
            if not await self.check_permit(interaction):
                return

        permitball = self.permit_users[user_id]

        # Incase it got hard deleted
        try:
            permitball = await BallInstance.get(id=permitball.id)
        except DoesNotExist:
            # Remove bad cache entry
            self.permit_users.pop(user_id, None)
            await log_action(
                f"{user_id}'s {permitball}: DELETED ERROR\nPopped from `self.permit_users`, retrying `self.check_permit`\n",
                interaction.client,
            )

            # Try verifying again
            if not await self.check_permit(interaction):
                return

            permitball = self.permit_users[user_id]

        # Incase it got soft deleted
        if permitball.deleted: #this will likely never be true, only used incase DoesNotExist did not trigger for soft deleted balls for any reason
            self.permit_users.pop(user_id, None)
            await log_action(
                f"{user_id}'s {permitball}: DELETED ERROR\nPopped from `self.permit_users`, retrying `self.check_permit`\n",
                interaction.client,
            )

            if not await self.check_permit(interaction):
                return

            permitball = self.permit_users[user_id]

        # Incase it got transferred by an admin
        user_player, _ = await Player.get_or_create(discord_id=user_id)
        
        if permitball.player_id != user_player.id:
            self.permit_users.pop(user_id, None)
            await log_action(
                f"{user_id}'s {permitball}: TRANSFERRED ERROR\nPopped from `self.permit_users`, retrying `self.check_permit`\n",
                interaction.client,
            )

            if not await self.check_permit(interaction):
                return

            permitball = self.permit_users[user_id]
        currentbuff = permitball.attack_bonus
        pricing = int(self.exponential_pricing(currentbuff+1))
        
        embed = discord.Embed(
            title=f"✨🌌 Special Buffs Upgrading 🌌✨",
            description=f"Upgrade Special Buffs to deal more in battles and boss battles!\nWorks on all specials."
        )
        embed.color=discord.Color.from_rgb(255,239,71)
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar.url)
        embed.add_field(
            name="CURRENT BUFF LEVEL:",
            value=f" **+{currentbuff}%**",
            inline=False
        )
        embed.add_field(
            name="NEXT BUFF LEVEL:",
            value=f" **+{currentbuff+1}%**\n\u200b",
            inline=False
        )

        embed.add_field(
            name="💰 Upgrade Cost:",
            value=f"**{pricing}** {currencyname}\n-# You can get {currencyname} by using the `/daily` command.\n\u200b",
            inline=False
        )
        
        embed.set_footer(
            text=f"Your special buffs are currently **boosted** an extra {currentbuff}% for you!⚡\n💡 Use `/special_buffs` to check your buffs for each special."
        )
        
        upgrade_button = discord.ui.Button(
            style=discord.ButtonStyle.primary, emoji="⏫", label="Upgrade"
        )

        explain_button = discord.ui.Button(
            style=discord.ButtonStyle.secondary, emoji="❓", label="Explain this to me!"
        )

        async def protected_callback(button_interaction: discord.Interaction):
            if button_interaction.user.id != user_id:
                await button_interaction.response.send_message(
                    "This button isn't for you!", ephemeral=True
                )
                return
            await self.buffupdate(button_interaction, permitball)

        async def explain_callback(button_interaction: discord.Interaction):
            if button_interaction.user.id != user_id:
                await button_interaction.response.send_message(
                    "`/upgrade explain` → `explain:/upgrade buffs`", ephemeral=True
                )
                return
            
            explain_button.disabled = True
            upgrade_button.disabled = True
            await button_interaction.response.edit_message(view=view)
            
            await self.explain_logic(
                button_interaction,
                "BUFF"
            )
            await asyncio.sleep(5)
            
            explain_button.disabled = False
            upgrade_button.disabled = False
            await button_interaction.followup.edit_message(message_id=button_interaction.message.id, view=view)

        upgrade_button.callback = protected_callback

        explain_button.callback = explain_callback

        view = discord.ui.View(timeout=60)
        
        view.add_item(upgrade_button)
        view.add_item(explain_button)

        await interaction.channel.send(
            embed=embed,
            view=view
        )

        await interaction.followup.send("Upgrader embed sent!")

    @currencycommands.command(name="admin_give",description=f"Give {currencyname.lower()} to another user (admin).")
    async def admin_give(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        n: app_commands.Range[int, 1, 10000]
    ):
        if interaction.user.id != 417286033487429633:
            return await interaction.response.send_message(":x:",ephemeral=True)

        await interaction.response.defer(thinking=True)
        togiveresult = {}
        amountgiven = n

        for d in reversed(ZENI_NOTES):
            if n >= d:
                count = n // d
                togiveresult[d] = count
                n -= d * count

        giventext = ""
        player, _ = await Player.get_or_create(discord_id=user.id)
        for value, amount in togiveresult.items():
            if amount > 0:
                for i in range(amount):
                    changetogive = self.get_zeni(value)
                    instance = await BallInstance.create(
                        ball=changetogive,
                        player=player,
                        special=None,
                        attack_bonus=0,
                        health_bonus=0,
                    )
                if value == 1 and currencyname == "Credits":
                    givecurrency = "Credit"
                else:
                    givecurrency = currencyname
                giventext += f"- Given {amount}× {value} {givecurrency}\n"
        if value == 1 and currencyname == "Credits":
            givecurrency = "Credit"
        else:
            givecurrency = currencyname
        embed = discord.Embed(
            title=f"{amountgiven} {givecurrency} admin given to {user}",
            description=giventext,
            color=discord.Color.from_rgb(36,135,33)
        )

        embed.set_footer(text=f"Use `/{currencyname.lower()} count` to check how much {currencyname.lower()} you now own!")
        embed.set_thumbnail(url=user.display_avatar.url)

        await log_action(
            f"{interaction.user} gave {amountgiven} {givecurrency} to {user}({user.id})\n",
            interaction.client,
        )

        await interaction.followup.send(embed=embed)

    @currencycommands.command(name="admin_count",description=f"Count the number of {currencyname.lower()} that a player has or how many exist in total. (admin)")
    @app_commands.checks.has_any_role(*settings.root_role_ids)
    async def admin_count(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
    ):
        if interaction.response.is_done():
            return
        
        assert interaction.guild

        await interaction.response.defer(ephemeral=True, thinking=True)

        zenibalance = await self.zeni_balance(user,False)
        zenitable = zenibalance[0]
        totalzeni = zenibalance[1]
        
        max_field1 = (8 if settings.bot_name == "dragonballdex" else 11)
        max_field2 = max(len(str(field2)) for field1,field2,field3 in zenitable) + 4
        max_field3 = max(len(str(field3)) for field1,field2,field3 in zenitable) + 4
        table = f"**Total {currencyname}**: {totalzeni}\n\n**{currencyname} Breakdown**:```\n"
        table += f"{'Name':<{max_field1}} | {'Count':<{max_field2}} | {f'Subtotal':<{max_field3}}\n"
        table += f"{'-'*max_field1}-+-{'-'*max_field2}-+-{'-'*max_field3}\n"
        use_credits = (settings.bot_name != "dragonballdex")
        for field1, field2, field3 in zenitable:
            currencyname1 = "Credit" if use_credits and field1 == 1 else currencyname
            field1zeni = f"{field1} {currencyname1}"
            table += f"{field1zeni:<{max_field1}} | {field2:<{max_field2}} | {field3:<{max_field3}}\n"
        table += "```"
        embed = discord.Embed(
            title=f"Total {currencyname} count",
            description=table,
            color=discord.Color.blurple(),
        )
        if user:
            iconurl = user.display_avatar.url
            authorname = user.display_name
        else:
            iconurl = self.bot.user.display_avatar.url
            authorname = settings.bot_name
        embed.set_author(
            name=authorname, icon_url=iconurl
        )
        await interaction.followup.send(embed=embed)

    @upgradecommands.command(name="leaderboard", description=f"Display leaderboard of highest special buff levels or most stat changes.")
    @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
    @app_commands.choices(
        option=[
            app_commands.Choice(name="Highest Special Buff Level", value="BUFF"),
            app_commands.Choice(name=f"Most {settings.collectible_name.capitalize()} Stat Changes", value="STAT"),
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        option: str,
    ):
        if interaction.response.is_done():
            return
        
        assert interaction.guild

        await interaction.response.defer(thinking=True)

        sfilters = {}
        permitball = self.get_permit()
        sfilters["ball"] = permitball
        sfilters["server_id"] = 1238814628327325716
        permitlist = await BallInstance.filter(**sfilters).prefetch_related("ball")

        permitlist.sort(key=lambda ball: ball.attack_bonus if option == "BUFF" else ball.health_bonus, reverse=True)

        leaderboardpermit = permitlist[:10]
        leaderboardtitle = "Top Users: Highest Special Buff Levels" if option == "BUFF" else f"Top Users: Most {settings.collectible_name.capitalize()} Stat Changes"

        user_ids = [await ball.player for ball in leaderboardpermit]
        users = await asyncio.gather(*[self.bot.fetch_user(uid) for uid in user_ids])
        
        leaderboarddescription = ""
        for n, (ball, user) in enumerate(zip(leaderboardpermit, users), start=1):
            subtext = "Buff Level:" if option=="BUFF" else "Changed"
            balldot = f"+**{ball.attack_bonus}% ⚡**" if option=="BUFF" else f"**{ball.health_bonus}** {settings.collectible_name} stats!"
            # wanting to add promo to other commands, and fix if stamements to one
            leaderboarddescription += f"**{n}. {user.name}** {subtext} {balldot}\n"
            
        embed = discord.Embed(
            title=f"🏆 {leaderboardtitle}",
            description=leaderboarddescription,
            color=discord.Color.from_rgb(178, 34, 34)
        )

        first_permit = leaderboardpermit[0]
        first_user = await self.bot.fetch_user(await first_permit.player)
        avatar_url = first_user.avatar.url 
        embed.set_thumbnail(url=avatar_url)

        explain_button = discord.ui.Button(
            style=discord.ButtonStyle.secondary, emoji="❓", label="Explain this to me!"
        )

        async def explain_callback(button_interaction: discord.Interaction):
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message(
                    "`/upgrade explain` → `explain:/upgrade leaderboard`", ephemeral=True
                )
                return
            
            explain_button.disabled = True
            await button_interaction.response.edit_message(view=view)
            
            await self.explain_logic(
                button_interaction,
                "LEAD"
            )
            await asyncio.sleep(5)
            
            explain_button.disabled = False
            await button_interaction.followup.edit_message(message_id=button_interaction.message.id, view=view)

        explain_button.callback = explain_callback

        view = discord.ui.View(timeout=60)
        
        view.add_item(explain_button)

        await interaction.followup.send(embed=embed, view=view)
    
    async def explain_logic(
        self,
        interaction,
        explain,
    ):
        titletext = "🔧 Upgrade System Guide"
        statsname = "🧬`/upgrade stats`"
        buffsname = "✨`/upgrade buffs`"
        leaderboardname = "🏆`/upgrade leaderboard`"
        if explain == None:
            descriptiontext = f"This guide explains how the **/upgrade** commands work and what each option does. These commands let you spend **{currencyname}** to improve your **{settings.plural_collectible_name}** and your special buffs."
        else:
            descriptiontext = "For the full guide, use `/upgrade explain` without selecting the `explain:` option"
        descriptiontext += "\n-------------------------------------------\n"
        if settings.bot_name == "dragonballdex":
            a_collectible = "a character"
            shinybuff = "80,000"
            shiny1 = "80,800"
            shiny10 = "88,000"
            mythicalbuff = "160,000"
            mythical1 = "161,600"
            mythical10 = "176,000"
        else:
            a_collectible = "an item"
            shinybuff = "5,000"
            shiny1 = "5,050"
            shiny10 = "5,500"
            mythicalbuff = "12,000"
            mythical1 = "12,120"
            mythical10 = "13,200"
        collectible = settings.collectible_name
        
        statstext = f"This command lets you **upgrade or downgrade {a_collectible}'s stats**.\n\n"
        statstext += f"**What you can change**\n"
        statstext += f"- **ATK (Attack Bonus)**\n- **HP (Health Bonus)**\n"
        statstext += f"You can change **one or both stats** in a single command."
        
        statsname2 = f"**How it works**"
        statstext2 = f"- You select a {collectible} and set a **new ATK and/or HP value**\n"
        statstext2 += f"- The cost is based on:\n"
        statstext2 += f"  - The {collectible}'s rarity\n"
        statstext2 += f"  - How big the stat change is (the bigger changes cost more)\n"
        statstext2 += f"- **Downgrading stats still cost {currencyname}**, so be careful before confirming."

        statsname3 = f"**Important notes**"
        statstext3 = f"- Each successful stat change is **recorded**.\n"
        statstext3 += f"- The total number of stat-changes you've made is tracked and used for the leaderboard.\n"
        statstext3 += f"- You must confirm the change before {currencyname} is spent."

        statsname4 = f"**Example**"
        statstext4 = f"- Changing a {collectible} from `+2 ATK / +7 HP` → `+20 ATK / +50 HP`\n"
        statstext4 += f"- You pay {currencyname}\n"
        statstext4 += f"- Your stat-changes count increases by **1**"


        buffstext = f"This command upgrades your **Special buffs**, which makes **your specials stronger**.\n\n"
        buffstext += f"**What are special buffs?**\n"
        buffstext += f"- Each special has a base buff value when used in battles.\n- For example: **- Shiny** → +{shinybuff} buff **- Mythical** → +{mythicalbuff} buff\n"
        buffstext += f"- Your **buff level increases these values by a percentage**."
        
        buffsname2 = f"**How buff levels work**"
        buffstext2 = f"- You start at **+0%**\n"
        buffstext2 += f"- Each upgrade increases your buff level by **+1%**\n"
        buffstext2 += f"- The percentage is applies to **all specials**"

        buffsname3 = f"**Example**"
        buffstext3 = f"- At **+1% buff level**: - Shiny: `{shinybuff} → {shiny1}` - Mythical: `{mythicalbuff} → {mythical1}`\n"
        buffstext3 += f"- At **+10% buff level**: - Shiny: `{shinybuff} → {shiny10}` - Mythical: `{mythicalbuff} → {mythical10}`"
        
        buffsname4 = f"**Cost scaling**"
        buffstext4 = f"- Upgrades cost {currencyname}\n"
        buffstext4 += f"- **Each level costs more than the last** (prices increase as you go)\n"
        buffstext4 += f"- You can use `/special_buffs` to track your current buffs for each special."

        leaderboardtext = f"This command shows the **Top 10 players** in two different categories.\n\n"
        leaderboardtext += f"**Leaderboard options**\n"
        leaderboardtext += f"- **Highest Special Buff Level**\n"
        leaderboardtext += f"  - Ranks players by their **buff level from** `/upgrade buffs`\n"
        leaderboardtext += f"  - Shows who has the strongest overall special buffs\n"
        leaderboardtext += f"- **Most {collectible} Stat Changes**\n"
        leaderboardtext += f"  - Ranks players by how many times they've used `upgrade stats`\n"
        leaderboardtext += f"  - Shows who has upgraded or changed {collectible.lower()} stats the most"
        
        zeniname = f"**💰 Getting {currencyname}**"
        zenitext = f"- You'll need {currencyname} for all upgrades.\n"
        zenitext += f"- Use the `/daily` command to earn {currencyname} (You must be in the main server)\n"
        zenitext += f"- Plan upgrades carefully, since **all purchases are non-refundable**"

        summaryname = f"**🔗 Summary**"
        summarytext = f"- `/upgrade stats` → Change ATK/HP of {collectible} (tracks total changes)\n"
        summarytext += f"- `/upgrade buffs` → Increase your special buffs\n"
        summarytext += f"- `/upgrade leaderboard` → See top players in buffs or stat changes\n"
        summarytext += f"Upgrade wisely and climb the leaderboard! 🔝"
        

        entries = []
        
        if explain == None or explain == "STAT":
            statsentry = (statsname, statstext)
            statsentry2 = (statsname2, statstext2)
            statsentry3 = (statsname3, statstext3)
            statsentry4 = (statsname4, statstext4)
            entries.append(statsentry)
            entries.append(statsentry2)
            entries.append(statsentry3)
            entries.append(statsentry4)
        
        if explain == None or explain == "BUFF":
            buffsentry = (buffsname, buffstext)
            buffsentry2 = (buffsname2, buffstext2)
            buffsentry3 = (buffsname3, buffstext3)
            buffsentry4 = (buffsname4, buffstext4)
            entries.append(buffsentry)
            entries.append(buffsentry2)
            entries.append(buffsentry3)
            entries.append(buffsentry4)
            
        if explain == None or explain == "LEAD":
            leaderboardentry = (leaderboardname, leaderboardtext)
            entries.append(leaderboardentry)
            
        zenientry = (zeniname, zenitext) # always show
        entries.append(zenientry)
        
        if explain == None:
            summaryentry = (summaryname, summarytext)
            entries.append(summaryentry)
            
        per_page = 4
        
        source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
        source.embed.title = titletext
        source.embed.description = descriptiontext
    
        source.embed.colour = discord.Colour.from_rgb(190,100,190)
        source.embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start(
            ephemeral=True,
        )           
    
    @upgradecommands.command(name="explain", description=f"Explain what the upgrade commands do.")
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    @app_commands.choices(
        explain=[
            app_commands.Choice(name="/upgrade stats", value="STAT"),
            app_commands.Choice(name="/upgrade buffs", value="BUFF"),
            app_commands.Choice(name="/upgrade leaderboard", value="LEAD"),
        ]
    )
    async def explain(
        self,
        interaction: discord.Interaction,
        explain: str | None = None,
    ):
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.explain_logic(interaction,explain)
