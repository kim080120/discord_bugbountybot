from __future__ import annotations

import json
import discord
from discord import app_commands

from ..services.policy_parser import extract_policy, dumps_extracted
from ..services.endpoint_triage import reclassify_program_endpoints
from ..workspace import find_program_channel, chunk_text


class PolicyCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="policy", description="Policy import and diff")
        self.bot = bot

    async def _import_text(self, interaction: discord.Interaction, program_name: str, source_type: str, source_name: str, text: str, apply: bool):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        extracted = extract_policy(text)
        sid = self.bot.db.add_policy_snapshot(
            program_id=program.id,
            source_type=source_type,
            source_name=source_name,
            raw_text=text,
            extracted_json=dumps_extracted(extracted),
        )

        added_in = added_out = added_res = 0
        if apply:
            for value in extracted["in_scope"]:
                self.bot.db.add_scope_item(program_id=program.id, type="in", value=value, note=f"policy import #{sid}", source_url=source_name)
                added_in += 1
            for value in extracted["out_scope"]:
                self.bot.db.add_scope_item(program_id=program.id, type="out", value=value, note=f"policy import #{sid}", source_url=source_name)
                added_out += 1
            for text_item in extracted["restrictions"]:
                self.bot.db.add_restriction(program_id=program.id, severity="medium", text=text_item, source_url=source_name)
                added_res += 1
            reclassify_program_endpoints(self.bot.db, program)

        ch = find_program_channel(self.bot, program, "notices")
        if ch:
            msg = (
                f"# Policy Import #{sid}\n"
                f"- Source: `{source_name}`\n"
                f"- Apply: `{apply}`\n"
                f"- Extracted in-scope: `{len(extracted['in_scope'])}`\n"
                f"- Extracted out-of-scope: `{len(extracted['out_scope'])}`\n"
                f"- Extracted restrictions: `{len(extracted['restrictions'])}`"
            )
            await ch.send(msg)
            for chunk in chunk_text("```json\n" + dumps_extracted(extracted) + "\n```", limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(
            f"Policy snapshot `#{sid}` saved. Extracted in `{len(extracted['in_scope'])}`, out `{len(extracted['out_scope'])}`, restrictions `{len(extracted['restrictions'])}`. Applied: `{apply}`.",
            ephemeral=True,
        )

    @app_commands.command(name="import_text", description="Import policy text and optionally apply extracted scope/restrictions")
    async def import_text(self, interaction: discord.Interaction, program_name: str, text: str, source_name: str = "manual", apply: bool = False):
        await interaction.response.defer(ephemeral=True)
        await self._import_text(interaction, program_name, "text", source_name, text, apply)

    @app_commands.command(name="import_file", description="Import policy from a txt/html/md attachment")
    async def import_file(self, interaction: discord.Interaction, program_name: str, file: discord.Attachment, apply: bool = False):
        await interaction.response.defer(ephemeral=True)
        if file.size > 2 * 1024 * 1024:
            await interaction.followup.send("Policy file too large. Limit is 2MB.", ephemeral=True)
            return
        data = await file.read()
        text = data.decode("utf-8", errors="replace")
        await self._import_text(interaction, program_name, "file", file.filename, text, apply)

    @app_commands.command(name="diff", description="Show latest two policy snapshot summary")
    async def diff(self, interaction: discord.Interaction, program_name: str):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return
        rows = self.bot.db.list_policy_snapshots(program.id, limit=2)
        if len(rows) < 2:
            await interaction.response.send_message("Need at least two policy snapshots for diff.", ephemeral=True)
            return
        latest = json.loads(rows[0]["extracted_json"])
        prev = json.loads(rows[1]["extracted_json"])
        added_in = sorted(set(latest.get("in_scope", [])) - set(prev.get("in_scope", [])))
        removed_in = sorted(set(prev.get("in_scope", [])) - set(latest.get("in_scope", [])))
        added_out = sorted(set(latest.get("out_scope", [])) - set(prev.get("out_scope", [])))
        removed_out = sorted(set(prev.get("out_scope", [])) - set(latest.get("out_scope", [])))
        msg = "\n".join([
            f"# Policy Diff — {program.name}",
            f"Latest `#{rows[0]['id']}` vs previous `#{rows[1]['id']}`",
            "",
            f"Added in-scope: {added_in or '-'}",
            f"Removed in-scope: {removed_in or '-'}",
            f"Added out-of-scope: {added_out or '-'}",
            f"Removed out-of-scope: {removed_out or '-'}",
        ])
        await interaction.response.send_message(msg[:1900], ephemeral=False)
