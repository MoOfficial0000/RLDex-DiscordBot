import discord
import logging
import random
import re
import tempfile
import traceback

from ballsdex.packages.countryballs.countryball import BallSpawnView
from datetime import datetime
from discord.utils import get
from discord import app_commands
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
    for i in range(1,10):
        currencycards.append(495+i) #495 main bot 195 test bot
else:
    T1Req = 80 #requirements for upgrading (cost for increasing a stat by 20%)
    T1Rarity = 1
    CommonReq = 5
    CommonRarity = 233
    LimitedReq = 200
    currencyname = "Credits"
    for i in ZENI_NOTES:
        if i == 1:
            currencycardname = f"1 Credit"
        else:
            currencycardname = f"{i} Credits"
        currencycard = [x for x in balls.values() if x.country==currencycardname][0]
        currencycards.append(currencycard.id)

gradient = (CommonReq-T1Req)/(CommonRarity-T1Rarity)
notallowed = ["zeni","credit","relic","dragon ball (","drop"]

class currency(commands.Cog):
    """
    Zeni commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.permit_users = set()

    currencycommands = app_commands.Group(
        name=currencyname.lower(), description=f'{currencyname} commands'
    )

    upgradecommands = app_commands.Group(
        name="upgrade", description=f'upgrade commands'
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
            await interaction.followup.send(f"You cannot afford this! You only have {totalzeni} {totalcurrency}", ephemeral=True)
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
        if permitcheck == 0:
            view = ConfirmChoiceView(
                interaction,
                accept_message=f"Confirmed, granting {currencyname} Permit...",
                cancel_message="Request cancelled.",
            )
            await interaction.followup.send(
                f"By using the upgrade commands you agree that ALL purchases are NON-REFUNDABLE.\nWould you like to continue? (You will recieve a permit that allows you to spend {currencyname} on upgrades.)",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if view.value:
                if user_id in self.permit_users: #incase someone uses the command multiple times
                    await interaction.followup.send(f"Error. You already have {currencyname} Permit.",ephemeral=True)
                    return False
                self.permit_users.add(user_id)
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
                await interaction.followup.send(
                    f"{currencyname} Permit successfully given.\nUse this command again to continue upgrading.",
                    ephemeral=True,
                )
                await log_action(
                    f"{interaction.user}({user_id}): Granted {permitinstance}\n",
                    interaction.client,
                )
            return False
        elif permitcheck > 1: #deleted duplicate permits
            permitlist = await BallInstance.filter(**pfilters).prefetch_related("ball")
            foundpermit = False
            for pb in permitlist:
                if pb.server_id != 1238814628327325716: #if it was given by admin or caught force caught
                    await pb.delete()
                else:
                    foundpermit = True
            if not foundpermit:
                return await self.check_permit(interaction)
            else:
                pfilters2 = {}
                permitball2 = self.get_permit()
                pfilters2["ball"] = permitball2
                pfilters2["player__discord_id"] = user_id
                permitcheck2 = await BallInstance.filter(**pfilters2).count()
                if permitcheck2 > 1:
                    await interaction.followup.send("You have found an ultra rare error!\nDm moofficial0 for a fix.") #very rare
                    await log_action(
                        f"⚠️ {interaction.user}({user_id}): ULTRA RARE ERROR (multi valid permits) ⚠️\n",
                        interaction.client,
                    )
                    return False
                else:
                    return True
        else:
            self.permit_users.add(user_id)
            return True

    @currencycommands.command(name="count",description=f"Count how much {currencyname} you own.")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def count(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            return
        
        assert interaction.guild

        await interaction.response.defer(ephemeral=True, thinking=True)

        zenibalance = await self.zeni_balance(interaction.user,False)
        zenitable = zenibalance[0]
        totalzeni = zenibalance[1]
        
        max_field1 = (8 if settings.bot_name == "dragonballdex" else 11)
        max_field2 = max(len(str(field2)) for field1,field2,field3 in zenitable) + 4
        max_field3 = max(len(str(field3)) for field1,field2,field3 in zenitable) + 4
        table = "```\n"
        table += f"{'Name':<{max_field1}} | {'Count':<{max_field2}} | {f'Subtotal':<{max_field3}}\n"
        table += f"{'-'*max_field1}-+-{'-'*max_field2}-+-{'-'*max_field3}\n"
        use_credits = (settings.bot_name != "dragonballdex")
        for field1, field2, field3 in zenitable:
            currencyname1 = "Credit" if use_credits and field1 == 1 else currencyname
            field1zeni = f"{field1} {currencyname1}"
            table += f"{field1zeni:<{max_field1}} | {field2:<{max_field2}} | {field3:<{max_field3}}\n"
        table += f"\n Total {currencyname}: {totalzeni}"
        table += "```"
        await interaction.followup.send(table)

    
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
            if await self.check_permit(interaction) == False:
                return
                
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
        if new_health_bonus is not None:
            new_health = new_health_bonus
            updates['health_bonus'] = new_health
            if new_health == old_health:
                return await interaction.followup.send(f"`new_health_bonus` cannot be the same as original health bonus")
            health_change = abs(new_health - old_health)
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
            f"You are planning to upgrade:\n{upgradetext}\nThis will cost {total_cost} {changecurrency}",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        
        await countryball.unlock() #unlocks after either ConfirmChoiceView timeouts, accepted or cancelled.
        
        if view.value:
            if await self.pay(interaction, total_cost):
                resultupgradetext = f"{settings.collectible_name.capitalize()} successfully upgraded!\n{upgradetext}"
                
                for key, value in updates.items():
                    setattr(countryball, key, value)
                await countryball.save()
                await interaction.followup.send(
                    resultupgradetext,
                    ephemeral=True,
                )
                resultlog = "Success ✅"
            else:
                resultlog = "Failed :x:"
            await log_action(
                f"{interaction.user}({user_id}): Upgrade {upgradetext}\n{total_cost} {changecurrency}\n{resultlog}",
                interaction.client,
            )

        
        


