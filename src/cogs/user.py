# Juste la partie de la commande leave à modifier

@commands.command(name="leave", help="Quitter la session en cours")
@checks.not_in_maintenance()
async def leave(self, ctx: commands.Context):
    join_row = await db.remove_participant(ctx.guild.id, ctx.author.id)
    if not join_row or join_row[0] is None:
        await ctx.send(f"🚫 {ctx.author.mention}, vous n'êtes pas inscrit.")
        return

    join_ts, mode = join_row
    end_ts = db.now_ts()
    elapsed = end_ts - join_ts
    
    # Calculer le temps de travail et de pause
    cycle = {"A": {"work": 50 * 60, "break": 10 * 60}, "B": {"work": 25 * 60, "break": 5 * 60}}
    work_duration = cycle[mode]["work"]
    break_duration = cycle[mode]["break"]
    total_cycle = work_duration + break_duration
    
    # Nombre de cycles complets
    complete_cycles = elapsed // total_cycle
    remaining_time = elapsed % total_cycle
    
    # Temps de travail effectif
    total_work = complete_cycles * work_duration
    if remaining_time <= work_duration:
        total_work += remaining_time
        total_pause = complete_cycles * break_duration
    else:
        total_work += work_duration
        total_pause = complete_cycles * break_duration + (remaining_time - work_duration)
    
    # Enregistrer le temps de travail
    await db.ajouter_temps(ctx.author.id, ctx.guild.id, total_work, mode, is_session_end=True)
    
    # Enregistrer la session détaillée
    await db.record_session(
        user_id=ctx.author.id,
        guild_id=ctx.guild.id,
        mode=mode,
        work_time=total_work,
        pause_time=total_pause,
        start_ts=join_ts,
        end_ts=end_ts
    )

    await ctx.send(
        f"👋 {ctx.author.mention} a quitté la session !\n"
        f"**Travail :** {format_seconds(total_work)}\n"
        f"**Pause :** {format_seconds(total_pause)}\n"
        f"**Total :** {format_seconds(elapsed)}\n"
        f"Bien joué ! 🎉"
    )
