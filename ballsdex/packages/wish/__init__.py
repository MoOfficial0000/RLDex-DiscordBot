from typing import TYPE_CHECKING

from ballsdex.packages.wish.cog import Wish

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(Wish(bot))
