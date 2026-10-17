import asyncio
import logging
import os
import uuid

import discord
import requests
from discord import app_commands

from api import (
    RECORD_COUNT,
    build_chart_level_index,
    fetch_user_best,
    fetch_user_brief,
)
from b50gen import build_jacket_index, create_image, get_album_cover
from database import get_user_id, get_linked_user_id, link_user, set_user_memory
from recommendation import RecommendationError, recommend_for_user

logger = logging.getLogger("tachy")


# Create and configure the Discord bot and commands.
def create_bot():
    intents = discord.Intents.default()
    bot = discord.Client(intents=intents)
    tree = app_commands.CommandTree(bot)

    @tree.command(
        name="link",
        description="Link your Arcaea account to Discord.",
    )
    @app_commands.describe(username="Arcaea username")
    async def link(interaction: discord.Interaction, username: str):
        arcaea_user_id = get_user_id(username)

        if arcaea_user_id is None:
            await interaction.response.send_message(
                f"Arcaea user '{username}' was not found.",
                ephemeral=True,
            )
            return

        link_user(interaction.user.id, username, arcaea_user_id)

        await interaction.response.send_message(
            f"Successfully linked to Arcaea user '{username}'.",
            ephemeral=True,
        )

    @tree.command(
        name="b50",
        description=f"Fetch your best {RECORD_COUNT} records.",
    )
    async def b50(interaction: discord.Interaction):
        arcaea_user_id = get_linked_user_id(interaction.user.id)

        if arcaea_user_id is None:
            await interaction.response.send_message(
                'Please link your Arcaea account first using "/link [username]".',
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            data = await asyncio.to_thread(fetch_user_best, arcaea_user_id)
        except (requests.RequestException, RuntimeError):
            logger.exception(
                "B%s API request failed for arcaea_user_id=%s",
                RECORD_COUNT,
                arcaea_user_id,
            )
            await interaction.followup.send("Failed to fetch data from the server.")
            return

        if not data:
            await interaction.followup.send("No records were found.")
            return

        filename_base = f"b{RECORD_COUNT}_{uuid.uuid4().hex}"
        image_path = None

        try:
            image_path = await asyncio.to_thread(
                create_image,
                data,
                filename_base,
            )

            try:
                profile = await asyncio.to_thread(
                    fetch_user_brief,
                    arcaea_user_id,
                )
            except (requests.RequestException, RuntimeError):
                logger.warning(
                    "Failed to fetch profile for arcaea_user_id=%s",
                    arcaea_user_id,
                )
                profile = None

            if profile:
                username = profile["name"]
                ptt = profile["rating_ptt"]

                description = f"Username: **{username}** · PTT: `{ptt:.2f}`"
            else:
                description = f"User ID: `{arcaea_user_id}`"

            filename = os.path.basename(image_path)

            embed = discord.Embed(
                title=f"Tachy's B{RECORD_COUNT} Generation",
                description=description,
                color=0x808080,
            )

            embed.set_image(url=f"attachment://{filename}")

            await interaction.followup.send(
                embed=embed,
                file=discord.File(
                    image_path,
                    filename=filename,
                ),
            )

        except Exception:
            logger.exception(
                "B%s image creation / sending failed for arcaea_user_id=%s",
                RECORD_COUNT,
                arcaea_user_id,
            )
            await interaction.followup.send(
                f"Failed to generate the B{RECORD_COUNT} image."
            )
        finally:
            if image_path and os.path.exists(image_path):
                os.remove(image_path)

    @tree.command(
        name="recommendations",
        description="Get three personalized Arcaea charts for training.",
    )
    async def recommendations_command(interaction: discord.Interaction):
        arcaea_user_id = get_linked_user_id(interaction.user.id)

        if arcaea_user_id is None:
            await interaction.response.send_message(
                'Please link your Arcaea account first using "/link [username]".',
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            recommendation_result = await asyncio.to_thread(
                recommend_for_user,
                arcaea_user_id,
            )
        except requests.RequestException:
            logger.exception(
                "Recommendation API/LLM request failed for arcaea_user_id=%s",
                arcaea_user_id,
            )
            await interaction.followup.send(
                "Failed to communicate with the Arcaea server or LLM server."
            )
            return
        except RecommendationError as exc:
            logger.warning(
                "Recommendation failed for arcaea_user_id=%s: %s",
                arcaea_user_id,
                exc,
            )
            await interaction.followup.send(f"Could not create a recommendation: {exc}")
            return
        except Exception:
            logger.exception(
                "Unexpected recommendation failure for arcaea_user_id=%s",
                arcaea_user_id,
            )
            await interaction.followup.send(
                "An unexpected error occurred while creating the recommendation."
            )
            return

        profile = recommendation_result["profile"]
        recommendations = recommendation_result["recommendations"]

        labels = {
            "warmup": "Warm-up",
            "base": "Base",
            "challenge": "Challenge",
        }

        colors = {
            "warmup": 0x4D96FF,
            "base": 0x57CC99,
            "challenge": 0xFF6B6B,
        }

        embeds = []
        files = []

        description = (
            f"Username: **{profile['name']}** · "
            f"PTT: `{profile['official_ptt']:.2f}`\n"
            f"Recommended CCs: "
            f"Warm-up `{profile['training_targets']['warmup_cc']:.2f}` / "
            f"Base `{profile['training_targets']['base_cc']:.2f}` / "
            f"Challenge `{profile['training_targets']['challenge_cc']:.2f}`"
        )

        header_embed = discord.Embed(
            title="Tachy's Recommendations",
            description=description,
            color=0x808080,
        )

        embeds.append(header_embed)

        for recommendation in recommendations:
            bucket = recommendation["bucket"]

            embed = discord.Embed(
                title=labels[bucket],
                color=colors[bucket],
            )

            embed.add_field(
                name=(
                    f"**{recommendation['song_name']}** — "
                    f"{recommendation['artist']}"
                ),
                value=(
                    f"{recommendation['difficulty_name']} "
                    f"{recommendation['display_level']} "
                    f"({recommendation['chart_constant']:.2f})"
                ),
                inline=False,
            )

            cover_path = get_album_cover(recommendation["song_id"])

            if cover_path and os.path.exists(cover_path):
                filename = f"daily_{bucket}_{uuid.uuid4().hex}.jpg"

                files.append(
                    discord.File(
                        cover_path,
                        filename=filename,
                    )
                )

                embed.set_thumbnail(url=f"attachment://{filename}")

            embeds.append(embed)

        await interaction.followup.send(
            embeds=embeds,
            files=files or None,
        )

    @tree.command(
        name="changemem",
        description="Change your Arcaea account's memory value.",
    )
    @app_commands.describe(memory="The new memory value")
    async def changemem(interaction: discord.Interaction, memory: int):
        arcaea_user_id = get_linked_user_id(interaction.user.id)

        if arcaea_user_id is None:
            await interaction.response.send_message(
                'Please link your Arcaea account first using "/link [username]".',
                ephemeral=True,
            )
            return

        if memory <= 0:
            await interaction.response.send_message(
                "Memory value must be a positive integer.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            success = await asyncio.to_thread(
                set_user_memory,
                arcaea_user_id,
                memory,
            )
        except Exception:
            logger.exception(
                "Failed to change memory for arcaea_user_id=%s",
                arcaea_user_id,
            )
            await interaction.followup.send(
                "Failed to update memory value.",
                ephemeral=True,
            )
            return

        if not success:
            await interaction.followup.send(
                f"Arcaea user '{arcaea_user_id}' was not found.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Successfully changed memory value to `{memory}`.",
            ephemeral=True,
        )

    @tree.command(
        name="ping",
        description="Check the bot's response time.",
    )
    async def ping(interaction: discord.Interaction):
        start_time = asyncio.get_running_loop().time()

        await interaction.response.send_message("Pong!")

        response_time = round((asyncio.get_running_loop().time() - start_time) * 1000)

        latency = round(bot.latency * 1000)

        await interaction.edit_original_response(
            content=f"Pong! `({latency}ms gateway, {response_time}ms response)`"
        )

    @bot.event
    async def on_ready():
        await asyncio.to_thread(build_chart_level_index)
        await asyncio.to_thread(build_jacket_index)
        await tree.sync()

        print(f"{bot.user} is ready!")

    return bot
