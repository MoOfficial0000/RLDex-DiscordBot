from typing import TYPE_CHECKING

from ballsdex.packages.extrapacks.cog import extraPacks #Import Class

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(extraPacks(bot))
