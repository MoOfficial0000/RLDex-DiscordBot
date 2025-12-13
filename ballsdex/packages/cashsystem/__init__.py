from typing import TYPE_CHECKING

from ballsdex.packages.currency.cog import currency #Import Class

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(currency(bot))
