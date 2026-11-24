/* Fixes from the review of bot and human match footage: respawn timing,
 * swimming and climbing out while fighting, the Grip answer during a climb
 * out, Force Jump flown from a standstill, the jump memory, Force Speed kept
 * up, and resupply after a Force Pull. Controlled fixtures only: synthetic
 * ground and hand-built graphs, not a level or a live match. */

static void test_fix_respawn(void)
{
    jkBot_Configure("Respawn_Test","ky.3do"); TacticsUse(0);
    memset(bot.previous,0,sizeof(bot.previous));
    bot.now=10; bot.deadAt=10;
    sithTime_g_msecGameTime=10000; sithControl_death_msgtimer=13000;
    assert(!Bot_RespawnPress() && "the stock code ignores the key until its message is due");
    sithTime_g_msecGameTime=12999; assert(!Bot_RespawnPress());
    sithTime_g_msecGameTime=13000; assert(Bot_RespawnPress());
    bot.previous[INPUT_FUNC_ACTIVATE]=1;
    assert(!Bot_RespawnPress() && "the release after a press is what respawns");
    bot.previous[INPUT_FUNC_ACTIVATE]=0; sithControl_death_msgtimer=0;
    assert(Bot_RespawnPress() && "once the message has shown the timer reads zero");
    /* Legacy: nothing for 1.5 s, then a 0.18 s press in every 1.4 s. */
    TacticsUse(1); sithControl_death_msgtimer=13000; sithTime_g_msecGameTime=13000;
    bot.now=11.0f; assert(!Bot_RespawnPress());
    bot.now=13.1f; assert(!Bot_RespawnPress() && "the old cadence misses the first window");
    bot.now=14.25f; assert(Bot_RespawnPress());
    TacticsUse(0); sithControl_death_msgtimer=0; sithTime_g_msecGameTime=0;
    puts("PASS quick respawn presses the moment the stock timer allows and releases on alternate frames; legacy keeps the slow cadence");
}

static void test_fix_swim_thrust(void)
{
    static SithSector pool;
    SithThing self={0}; SithPlayer own={0};
    memset(&pool,0,sizeof(pool)); pool.flags=SITH_SECTOR_UNDERWATER;
    jkBot_Configure("Stroke_Test","ky.3do"); TacticsUse(0);
    self.type=SITH_THING_PLAYER; self.sector=&pool; self.actorParams.pPlayer=&own;
    PlainFace(&self,0);
    /* Straight to the body's right while looking ahead: strafe alone, full key. */
    memset(bot.axes,0,sizeof(bot.axes)); memset(bot.keys,0,sizeof(bot.keys));
    Bot_SwimThrust(&self,(rdVector3){0,-1,0});
    assert(bot.axes[INPUT_FUNC_FORWARD]==0 && bot.axes[INPUT_FUNC_SLIDE]==1 &&
           !bot.keys[INPUT_FUNC_JUMP] && !bot.keys[INPUT_FUNC_DUCK]);
    /* Ahead and to the right: forward and strafe in the stock 1 : 0.7 ratio,
       so the thrust they make points exactly along the wanted line. */
    Bot_SwimThrust(&self,(rdVector3){0.8660254f,-0.5f,0});
    flex_t f=bot.axes[INPUT_FUNC_FORWARD], s=bot.axes[INPUT_FUNC_SLIDE];
    assert(fabsf(f-0.8660254f)<1e-4f && fabsf(s*0.7f-0.5f)<1e-4f);
    /* Down: crouch. Up: jump, but never on the surface, where a fresh jump
       press is the leap out of the water. */
    Bot_SwimThrust(&self,(rdVector3){0,0,-1});
    assert(bot.keys[INPUT_FUNC_DUCK] && !bot.keys[INPUT_FUNC_JUMP]);
    Bot_SwimThrust(&self,(rdVector3){0,0,1});
    assert(bot.keys[INPUT_FUNC_JUMP] && !bot.keys[INPUT_FUNC_DUCK]);
    self.physicsParams.flags=SITH_PF_ONWATERSURFACE;
    Bot_SwimThrust(&self,(rdVector3){0,0,1});
    assert(!bot.keys[INPUT_FUNC_JUMP] && !bot.keys[INPUT_FUNC_DUCK] && "no stray leap at the surface");
    self.physicsParams.flags=0;
    /* Looking up 30 degrees tilts the forward stroke upward; a level leg
       crouches against it. On the surface the head tilts nothing. */
    self.actorParams.headPYR.x=30;
    Bot_SwimThrust(&self,(rdVector3){1,0,0});
    assert(bot.axes[INPUT_FUNC_FORWARD]==1 && bot.keys[INPUT_FUNC_DUCK] && !bot.keys[INPUT_FUNC_JUMP]);
    self.physicsParams.flags=SITH_PF_ONWATERSURFACE;
    Bot_SwimThrust(&self,(rdVector3){1,0,0});
    assert(bot.axes[INPUT_FUNC_FORWARD]==1 && !bot.keys[INPUT_FUNC_DUCK]);
    self.physicsParams.flags=0;
    /* Looking steeply up or down: the route's own keys stand. */
    self.actorParams.headPYR.x=75; bot.axes[INPUT_FUNC_FORWARD]=0.3f; bot.axes[INPUT_FUNC_SLIDE]=0;
    Bot_SwimThrust(&self,(rdVector3){0,-1,0});
    assert(bot.axes[INPUT_FUNC_FORWARD]==0.3f && bot.axes[INPUT_FUNC_SLIDE]==0);
    self.actorParams.headPYR.x=0;
    /* Nothing left to swim: stop the stroke. */
    Bot_SwimThrust(&self,(rdVector3){0.01f,0,0});
    assert(bot.axes[INPUT_FUNC_FORWARD]==0 && bot.axes[INPUT_FUNC_SLIDE]==0);
    puts("PASS swim stroke solved for the view: forward, strafe at 0.7, jump and crouch; no surface leap, pitched view countered, steep view left to the route");
}

static flex_t ExitTurn(SithThing *self,rdVector3 bank,rdVector3 line)
{
    bot.rawTurn=bot.rawPitch=0; memset(bot.axes,0,sizeof(bot.axes));
    Bot_ExitAim(self,bank,line);
    return bot.rawTurn;
}

static rdVector3 ExitAt(flex_t degrees)
{
    return (rdVector3){5.0f*cosf(degrees/BOT_DEG),5.0f*sinf(degrees/BOT_DEG),0};
}

static void test_fix_water_exit(void)
{
    static SithSector pool,bank;
    static rdModel3 rifleModel;
    SithThing self={0},peer={0}; SithPlayer own={0},theirs={0}; jkPlayerInfo remote={0};
    memset(&pool,0,sizeof(pool)); memset(&bank,0,sizeof(bank)); pool.flags=SITH_SECTOR_UNDERWATER;
    strcpy(rifleModel.filename,"strg.3do");
    jkBot_Configure("Exit_Test","ky.3do"); TacticsUse(0); bot.now=5; bot.frameDt=1.0f; bot.elite=1;
    jkPlayer_maxPlayers=0; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    self.type=SITH_THING_PLAYER; self.sector=&pool; self.actorParams.pPlayer=&own; self.actorParams.health=100;
    self.moveSize=self.collideSize=0.065f; self.idx=1; self.actorParams.maxRotVelocity=200;
    sithPlayer_g_pLocalPlayerThing=&self;
    rdVector3 line={1,0,0}, bankAim={2,0,0};

    /* Headed for the climb: within 43 degrees of the line to the bank, facing
       either way along it, since forward and strafe together still push at
       full thrust. Legacy insisted on facing the bank, level. */
    PlainFace(&self,40/BOT_DEG); assert(Bot_ExitHeaded(&self,line));
    PlainFace(&self,50/BOT_DEG); assert(!Bot_ExitHeaded(&self,line));
    PlainFace(&self,3.14159265f); assert(Bot_ExitHeaded(&self,line) && "backing out pushes as hard");
    TacticsUse(1); PlainFace(&self,40/BOT_DEG); assert(!Bot_ExitHeaded(&self,line));
    PlainFace(&self,0); assert(Bot_ExitHeaded(&self,line)); TacticsUse(0);

    /* The look while climbing: as near the shot as that cone allows. */
    self.physicsParams.flags=SITH_PF_ONWATERSURFACE; PlainFace(&self,0);
    nav.exitLookValid=1;
    nav.exitLook=ExitAt(30);  assert(fabsf(ExitTurn(&self,bankAim,line)-30.0f)<0.05f && "inside the cone: on the shot");
    nav.exitLook=ExitAt(90);  assert(fabsf(ExitTurn(&self,bankAim,line)-0.75f*BOT_DEG)<0.05f && "clamped to the cone's edge");
    nav.exitLook=ExitAt(-90); assert(fabsf(ExitTurn(&self,bankAim,line)+0.75f*BOT_DEG)<0.05f);
    nav.exitLook=ExitAt(120);
    assert(fabsf(ExitTurn(&self,bankAim,line)-(180.0f-0.75f*BOT_DEG))<0.05f && "the backward cone serves too");
    nav.exitLook=ExitAt(180); assert(fabsf(fabsf(ExitTurn(&self,bankAim,line))-180.0f)<0.05f && "a shot behind: back out");
    /* Under the surface the head tilts the stroke: face the bank, level. */
    self.physicsParams.flags=0; nav.exitLook=ExitAt(90);
    assert(fabsf(ExitTurn(&self,bankAim,line))<0.05f);
    self.physicsParams.flags=SITH_PF_ONWATERSURFACE; nav.exitLookValid=0;
    assert(fabsf(ExitTurn(&self,bankAim,line))<0.05f && "no fight: face the bank");

    /* One launch spot, one swimmer: the nearer one keeps it. */
    BotNode *wet=&bot.nodes[0], *dry=&bot.nodes[1];
    bot.nNodes=2; memset(wet,0,sizeof(*wet)); memset(dry,0,sizeof(*dry));
    wet->pos=(rdVector3){0,0,0}; wet->sector=&pool; dry->pos=(rdVector3){0.6f,0,0.3f}; dry->sector=&bank;
    nav.waterExitStart=wet->pos; self.position=(rdVector3){0.10f,0,0};
    jkPlayer_maxPlayers=2; jkPlayer_playerInfos[1].flags=1; jkPlayer_playerInfos[1].playerNetId=77;
    jkPlayer_playerInfos[1].pLocalPlayer=&peer;
    peer.type=SITH_THING_PLAYER; peer.moveSize=peer.collideSize=0.065f; peer.idx=2; peer.sector=&pool;
    peer.actorParams.pPlayer=&theirs; peer.actorParams.health=100; peer.playerInfo=&remote;
    remote.rd_thing.model3=&rifleModel;
    peer.position=(rdVector3){0.05f,0,0}; assert(Bot_ExitTaken(&self,dry) && "nearer the spot");
    peer.position=(rdVector3){-0.20f,0,0}; assert(!Bot_ExitTaken(&self,dry) && "farther from it");
    peer.position=(rdVector3){-0.10f,0,0}; assert(!Bot_ExitTaken(&self,dry));
    peer.idx=0; assert(Bot_ExitTaken(&self,dry) && "a tie goes to the lower slot"); peer.idx=2;
    peer.position=(rdVector3){0.05f,0,0.5f}; assert(!Bot_ExitTaken(&self,dry) && "not on this level");
    peer.position=dry->pos; assert(Bot_ExitTaken(&self,dry) && "standing on the landing");
    peer.flags=SITH_TF_DEAD; assert(!Bot_ExitTaken(&self,dry)); peer.flags=0;

    /* Taken: the climb gives way, the spot is set aside, the plan moves on. */
    nav.jumpVelocity=self.actorParams.jumpSpeed=1.5f;
    self.physicsParams.flags=SITH_PF_USETHRUST|SITH_PF_USEGRAVITY|SITH_PF_ONWATERSURFACE;
    self.physicsParams.mass=1; self.actorParams.maxThrust=2;
    nav.waterExitFrom=0; nav.waterExitTo=1; nav.waterExitPhase=0; nav.waterExitUntil=bot.now+4;
    peer.position=(rdVector3){0.05f,0,0}; bot.goal=1; bot.routeCount=1; bot.tele.exitYields=0;
    Bot_ExitWaterMove(&self);
    assert(bot.tele.exitYields==1 && nav.waterExitUntil==0 && bot.goal==-1 && dry->avoidUntil>bot.now+3.9f);
    TacticsUse(1); dry->avoidUntil=0; nav.waterExitUntil=bot.now+4; bot.goal=1;
    Bot_ExitWaterMove(&self);
    assert(bot.tele.exitYields==1 && nav.waterExitUntil>0 && bot.goal==1 && "legacy shoves on");
    TacticsUse(0); nav.waterExitUntil=0;

    /* A heavy gun waits out the run-up, the jump and the settle on the spot. */
    nav.waterExitUntil=bot.now+4; self.position=(rdVector3){0.02f,0,0};
    nav.waterExitPhase=1;
    assert(Bot_ExitHoldsFire(&self,SITHBIN_CONCUSSION_RIFLE) && Bot_ExitHoldsFire(&self,SITHBIN_RAIL_DETONATOR));
    assert(!Bot_ExitHoldsFire(&self,SITHBIN_STORMTROOPER_RIFLE) && !Bot_ExitHoldsFire(&self,SITHBIN_REPEATER));
    nav.waterExitPhase=2; assert(Bot_ExitHoldsFire(&self,SITHBIN_CONCUSSION_RIFLE));
    nav.waterExitPhase=0; assert(Bot_ExitHoldsFire(&self,SITHBIN_CONCUSSION_RIFLE) && "settled on the spot");
    self.position=(rdVector3){0.30f,0,0}; assert(!Bot_ExitHoldsFire(&self,SITHBIN_CONCUSSION_RIFLE) && "still swimming in");
    nav.waterExitUntil=0; assert(!Bot_ExitHoldsFire(&self,SITHBIN_CONCUSSION_RIFLE));

    /* The whole climb: a rifle fires at a visible opponent while the climb
       goes on and turns into the cone. Legacy climbs blind. */
    /* The opponent stands 70 degrees off the line to the bank; the bot faces
       it, so the climb must turn it back to the cone's edge at 43. */
    self.position=(rdVector3){0.30f,0,0};
    peer.position=(rdVector3){0.30f+2.5f*cosf(70/BOT_DEG),2.5f*sinf(70/BOT_DEG),0};
    own.curWeaponID=SITHBIN_STORMTROOPER_RIFLE;
    own.aItems[SITHBIN_STORMTROOPER_RIFLE].amount=1; own.aItems[SITHBIN_STORMTROOPER_RIFLE].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_ENERGY].amount=100;
    PlainFace(&self,70/BOT_DEG);
    nav.waterExitPhase=0; nav.waterExitUntil=bot.now+4; bot.reactionUntil=0; bot.nextForce=0; bot.forceBin=-1;
    testLOS=1; memset(bot.keys,0,sizeof(bot.keys)); bot.rawTurn=0;
    Bot_ContinueWaterExit(&self,&peer);
    assert(bot.keys[INPUT_FUNC_FIRE1] && nav.waterExitUntil>0 && "shooting on the way out");
    assert(fabsf(bot.rawTurn-(0.75f*BOT_DEG-70.0f))<0.5f && "turning back into the climbing cone");
    TacticsUse(1); memset(bot.keys,0,sizeof(bot.keys)); bot.reactionUntil=0; nav.waterExitUntil=bot.now+4;
    Bot_ContinueWaterExit(&self,&peer);
    assert(!bot.keys[INPUT_FUNC_FIRE1] && !bot.keys[INPUT_FUNC_FIRE2]);
    TacticsUse(0);

    /* A Grip is answered even mid-climb; nothing else is cast until dry. */
    own.aItems[SITHBIN_F_ABSORB].amount=4; own.aItems[SITHBIN_F_ABSORB].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_FORCEMANA].amount=250; bot.forceEnabled=1;
    nav.waterExitUntil=bot.now+4; bot.forceBin=-1; bot.nextForce=0; bot.grippedUntil=0;
    memset(bot.keys,0,sizeof(bot.keys)); Bot_ForceTick(&self,&peer,0);
    assert(bot.forceBin<0 && "not gripped: the climb comes first");
    bot.grippedUntil=bot.now+0.8f; Bot_ForceTick(&self,&peer,0);
    assert(bot.forceBin==SITHBIN_F_ABSORB && bot.keys[Bot_PowerKey(SITHBIN_F_ABSORB)]);
    bot.forceBin=-1; bot.nextForce=0; bot.grippedUntil=0; nav.waterExitUntil=0;
    /* Held by Grip with Absorb up: no Pull, so the mana is there to raise
       Absorb again when it runs out. Without the Grip the Pull goes out. */
    own.aItems[SITHBIN_F_ABSORB].state|=SITHINVENTORY_ITEM_ACTIVATED; own.aItems[SITHBIN_FORCEMANA].amount=300;
    own.aItems[SITHBIN_F_PULL].amount=4; own.aItems[SITHBIN_F_PULL].state=SITHINVENTORY_ITEM_AVAILABLE;
    static SithCogSymbol pullMarker; static SithCogSymbolTable pullTable; static sithCog pullCog;
    memset(&pullMarker,0,sizeof(pullMarker)); memset(&pullTable,0,sizeof(pullTable)); memset(&pullCog,0,sizeof(pullCog));
    pullMarker.pName="victim"; pullMarker.val.type=COG_TYPE_INT; pullMarker.val.data[0]=-1;
    pullTable.aSymbols=&pullMarker; pullTable.tableSize=pullTable.numUsedSymbols=1; pullCog.pSymbolTable=&pullTable;
    testInventoryTypes[SITHBIN_F_PULL].cog=&pullCog;
    peer.position=(rdVector3){self.position.x+1.0f,self.position.y,self.position.z};
    PlainFace(&self,0); bot.competitiveForce=1; bot.reactionUntil=0;
    bot.grippedUntil=bot.now+0.8f; memset(bot.keys,0,sizeof(bot.keys)); Bot_ForceTick(&self,&peer,0);
    assert(bot.forceBin<0 && "held by Grip: no Pull");
    bot.grippedUntil=0; bot.nextForce=0; Bot_ForceTick(&self,&peer,0);
    assert(bot.forceBin==SITHBIN_F_PULL && "free again: the Pull goes out");
    testInventoryTypes[SITHBIN_F_PULL].cog=NULL; bot.competitiveForce=0;
    bot.forceBin=-1; bot.nextForce=0; bot.grippedUntil=0; nav.waterExitUntil=0;
    memset(own.aItems,0,sizeof(own.aItems));
    self.physicsParams.flags=0; jkPlayer_maxPlayers=0; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    sithPlayer_g_pLocalPlayerThing=NULL; bot.nNodes=0; bot.frameDt=0.02f;
    puts("PASS climb out: full-thrust cone, look clamped toward the shot, one swimmer per spot, heavy guns held, rifle fire on the way out, Grip still answered");
}

static void test_fix_force_jump(void)
{
    static SithWorld world;
    SithThing self; SithPlayer own;
    testPlainActive=1; plainEdge=plainWall=1e9f; plainGround.flags=0; plainLand.flags=0;
    PlainSelf(&self,&own); self.physicsParams.airDrag=0.5f;
    jkBot_Configure("Leap_Test","ky.3do"); TacticsUse(0);
    bot.world=sithWorld_g_pCurrentWorld=&world; world.gravity=4.0f;
    bot.physicsStep=1.0f/150.0f; bot.frameDt=1.0f/30.0f; nav.maxRunSpeed=1.33f;
    sithPlayer_g_pLocalPlayerThing=&self;
    flex_t seconds,hold,legacyHold;
    /* Level and slightly lower landings are flown through the standstill model
       too; before, only higher ones were. */
    BotNode a={.pos={0,0,BOT_FOOT_HEIGHT},.sector=&plainLand}, level={.pos={0.35f,0,BOT_FOOT_HEIGHT},.sector=&plainLand};
    assert(Bot_FullForceJump(&a,&level,0.25f,&seconds) && seconds>1.0f);
    TacticsUse(1); assert(!Bot_FullForceJump(&a,&level,0.25f,&seconds)); TacticsUse(0);
    /* A shelf 0.45 up behind a sheer face 0.12 away, landing 0.3 out. The
       old low arc assumed running speed through the air and took it with the
       lightest hold at any rank. From a standstill only air thrust carries the
       jumper over the lip, and only a long flight gives it time to: the light
       hold rises along the face and drops back beside it. */
    plainShelf=0.12f; plainShelfZ=0.45f;
    BotNode shelf={.pos={0.30f,0,0.45f+BOT_FOOT_HEIGHT},.sector=&plainLand};
    TacticsUse(1);
    assert(Bot_ForceJumpProfile(&a,&shelf,4,&seconds,&legacyHold) && legacyHold==0.25f);
    assert(Bot_ForceJumpProfile(&a,&shelf,1,&seconds,&legacyHold) && legacyHold==0.25f && "legacy promises it at rank one");
    TacticsUse(0);
    assert(!Bot_FullForceJump(&a,&shelf,0.25f,&seconds) && "the light hold falls back beside the face");
    assert(Bot_ForceJumpProfile(&a,&shelf,4,&seconds,&hold) && fabsf(hold-1.40f)<0.001f && seconds>1.5f);
    assert(Bot_ForceJumpProfile(&a,&shelf,3,&seconds,&hold) && fabsf(hold-1.05f)<0.001f);
    assert(!Bot_ForceJumpProfile(&a,&shelf,2,&seconds,&hold) && !Bot_ForceJumpProfile(&a,&shelf,1,&seconds,&hold));
    /* The same shelf half a unit off is out of reach from a standstill at any
       rank; a running jump is the only way, and that is a different leg. */
    plainShelf=0.5f; shelf.pos.x=0.75f;
    TacticsUse(1); assert(Bot_ForceJumpProfile(&a,&shelf,4,&seconds,&legacyHold)); TacticsUse(0);
    assert(!Bot_ForceJumpProfile(&a,&shelf,4,&seconds,&hold));
    /* jump_memory: up on the target's level, a walk from the mark, is made;
       still on the ground below is a miss. */
    bot.nNodes=2; memset(bot.nodes,0,2*sizeof(bot.nodes[0]));
    bot.nodes[0].pos=a.pos; bot.nodes[0].sector=&plainLand;
    bot.nodes[1].pos=(rdVector3){1.2f,0,0.45f+BOT_FOOT_HEIGHT}; bot.nodes[1].sector=&plainLand;
    memset(nav.failedJumps,0,sizeof(nav.failedJumps)); bot.tele.jumpMisses=0; bot.now=10;
    self.sector=&plainLand; self.position=(rdVector3){0.65f,0,0.45f+BOT_FOOT_HEIGHT};
    nav.jumpFrom=1; nav.jumpTo=2; nav.jumpTarget=bot.nodes[1].pos; Bot_JumpLanded(&self);
    assert(bot.tele.jumpMisses==0 && !Bot_JumpFailed(0,1) && "on the ledge, 0.55 from the mark");
    self.position=(rdVector3){0.40f,0,BOT_FOOT_HEIGHT};
    nav.jumpFrom=1; nav.jumpTo=2; nav.jumpTarget=bot.nodes[1].pos; Bot_JumpLanded(&self);
    assert(bot.tele.jumpMisses==1 && Bot_JumpFailed(0,1) && "below it");
    memset(nav.failedJumps,0,sizeof(nav.failedJumps)); bot.tele.jumpMisses=0; bot.nNodes=0;
    for (int i=0;i<BOT_NODES && i<4;i++) bot.nodes[i].avoidUntil=0;
    /* Following such a leg: the route moves on to the landing node once the
       bot is within 0.11 of the launch node, and from there the standstill
       flight may not make it. The bot steps onto the launch spot, facing the
       landing, and jumps from there. Before, it walked on into the face. */
    plainShelf=0.12f; shelf.pos.x=0.30f;
    bot.nNodes=2; memset(bot.nodes,0,2*sizeof(bot.nodes[0]));
    bot.nodes[0].pos=a.pos; bot.nodes[0].sector=&plainLand; bot.nodes[0].item=-1;
    bot.nodes[1]=shelf; bot.nodes[1].item=-1;
    bot.nodes[0].nEdges=1; bot.nodes[0].edges[0]=(BotEdge){1,1.0f,BOT_ROUTE_FORCEJUMP};
    bot.graphDone=1; bot.forceEnabled=1; bot.now=20; bot.nextJump=0; sithTime_g_secGameTime=20;
    own.aItems[SITHBIN_F_JUMP].amount=4; own.aItems[SITHBIN_F_JUMP].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_FORCEMANA].amount=400;
    #define LEAP_ROUTE() (bot.goal=1, bot.route[0]=0, bot.route[1]=1, bot.routePos=1, bot.routeCount=2, \
        bot.nextPlan=bot.now+100, bot.forceBin=-1, bot.nextForce=0, nav.forceJumpPending=0, nav.jumpUntil=0, \
        memset(bot.axes,0,sizeof(bot.axes)), memset(bot.keys,0,sizeof(bot.keys)))
    LEAP_ROUTE(); self.position=(rdVector3){-0.10f,0,BOT_FOOT_HEIGHT};
    assert(!Bot_ForceJumpProfile(&(BotNode){.pos=self.position,.sector=&plainLand},&shelf,4,&seconds,&hold));
    Bot_Navigate(&self);
    assert(bot.forceBin<0 && !nav.forceJumpPending && bot.axes[INPUT_FUNC_FORWARD]>0.1f && bot.goal==1 && "step onto the spot");
    LEAP_ROUTE(); self.position=a.pos; Bot_Navigate(&self);
    assert(nav.forceJumpPending && bot.forceBin==SITHBIN_F_JUMP && fabsf(bot.forceUntil-bot.now-1.40f)<0.001f && "jump from it");
    /* Legacy walks on toward the landing without a jump. */
    TacticsUse(1); LEAP_ROUTE(); self.position=(rdVector3){-0.10f,0,BOT_FOOT_HEIGHT}; bot.nextJump=0;
    Bot_Navigate(&self); assert(bot.forceBin==SITHBIN_F_JUMP || bot.axes[INPUT_FUNC_FORWARD]>0.1f); TacticsUse(0);
    /* A leg that cannot be made even from the spot is struck off at once. */
    plainShelf=0.5f; bot.nodes[1].pos.x=0.75f; memset(nav.failedJumps,0,sizeof(nav.failedJumps));
    LEAP_ROUTE(); self.position=a.pos; bot.nextJump=0; Bot_Navigate(&self);
    assert(bot.forceBin<0 && bot.goal==-1 && Bot_JumpFailed(0,1) && "struck, not walked into the wall");
    /* And so is one the bot cannot get back onto the spot for. */
    plainShelf=0.12f; bot.nodes[1].pos.x=0.30f; memset(nav.failedJumps,0,sizeof(nav.failedJumps));
    LEAP_ROUTE(); self.position=(rdVector3){-0.10f,0,BOT_FOOT_HEIGHT}; Bot_Navigate(&self); assert(bot.goal==1);
    bot.now+=3.1f; LEAP_ROUTE(); Bot_Navigate(&self); assert(bot.goal==-1 && Bot_JumpFailed(0,1));
    #undef LEAP_ROUTE
    memset(nav.failedJumps,0,sizeof(nav.failedJumps)); bot.nNodes=0; bot.goal=-1; bot.routeCount=bot.routePos=0;
    nav.forceJumpPending=0; bot.forceBin=-1; memset(own.aItems,0,sizeof(own.aItems));
    plainShelf=1e9f; plainShelfZ=0; testPlainActive=0;
    bot.world=sithWorld_g_pCurrentWorld=NULL; sithPlayer_g_pLocalPlayerThing=NULL;
    puts("PASS Force Jump legs flown from a standstill: level landings checked, a shelf the old arc took lightly needs a long hold and rank three, a far shelf is refused; the bot steps onto the launch spot or strikes the leg");
}

static void test_fix_jump_memory(void)
{
    static SithSector land; static SithWorld world;
    static flex_t distance[BOT_NODES]; static int parent[BOT_NODES];
    SithThing self={0}; SithPlayer own={0};
    memset(&land,0,sizeof(land));
    jkBot_Configure("JumpMemory_Test","ky.3do"); TacticsUse(0); bot.now=5; jkPlayer_maxPlayers=0;
    self.type=SITH_THING_PLAYER; self.sector=&land; self.actorParams.pPlayer=&own; self.actorParams.health=100;
    bot.world=sithWorld_g_pCurrentWorld=&world; world.numThings=0; world.numThingsLoaded=0;
    bot.graphDone=1; bot.nNodes=4;
    WaterNode(0,0,&land,-1); WaterNode(1,1.0f,&land,-1); WaterNode(2,1.5f,&land,-1); WaterNode(3,5,&land,-1);
    bot.nodes[1].pos.z=bot.nodes[2].pos.z=0.5f; /* the ledge */
    bot.nodes[0].nEdges=2;
    bot.nodes[0].edges[0]=(BotEdge){1,1.2f,BOT_ROUTE_JUMP};
    bot.nodes[0].edges[1]=(BotEdge){3,5.0f,BOT_ROUTE_WALK};
    memset(nav.failedJumps,0,sizeof(nav.failedJumps));
    /* Landed under the ledge, not on it. */
    self.position=(rdVector3){0.9f,0,0};
    nav.jumpFrom=1; nav.jumpTo=2; nav.jumpTarget=bot.nodes[1].pos; bot.goal=1; bot.routeCount=1; bot.tele.jumpMisses=0;
    Bot_JumpLanded(&self);
    assert(bot.tele.jumpMisses==1 && bot.goal==-1 && bot.routeCount==0 && !nav.jumpFrom && !nav.jumpTo);
    assert(Bot_JumpFailed(0,1) && !Bot_JumpFailed(1,0));
    assert(bot.nodes[1].avoidUntil>bot.now+29 && bot.nodes[2].avoidUntil>bot.now+29 && "the whole ledge is set aside");
    assert(bot.nodes[0].avoidUntil<=bot.now && bot.nodes[3].avoidUntil<=bot.now);
    Bot_PathDistances(&self,0,distance,parent);
    assert(distance[1]>1e19f && fabsf(distance[3]-5.0f)<0.0005f && "the failed leg is off the map");
    bot.now+=31; assert(Bot_JumpFailed(0,1) && "the leg itself stays struck for twice as long");
    bot.now+=30; assert(!Bot_JumpFailed(0,1));
    Bot_PathDistances(&self,0,distance,parent); assert(fabsf(distance[1]-1.2f)<0.0005f);
    /* A landing on the mark is not a miss. */
    self.position=(rdVector3){1.1f,0,0.5f}; nav.jumpFrom=1; nav.jumpTo=2; nav.jumpTarget=bot.nodes[1].pos;
    Bot_JumpLanded(&self); assert(bot.tele.jumpMisses==1 && !Bot_JumpFailed(0,1));
    /* The legacy table keeps no memory. */
    TacticsUse(1); self.position=(rdVector3){0.9f,0,0}; nav.jumpFrom=1; nav.jumpTo=2;
    Bot_JumpLanded(&self); assert(bot.tele.jumpMisses==1 && !Bot_JumpFailed(0,1));
    TacticsUse(0); bot.nNodes=0; bot.world=sithWorld_g_pCurrentWorld=NULL;
    puts("PASS jump memory: a miss strikes the leg and its ledge, the planner routes around it until the memory lapses, a clean landing and legacy record nothing");
}

static void test_fix_speed(void)
{
    static SithWorld world;
    SithThing self; SithPlayer own;
    testPlainActive=1; plainEdge=plainWall=plainShelf=1e9f; plainGround.flags=0; plainLand.flags=0;
    PlainSelf(&self,&own);
    jkBot_Configure("Speed_Test","ky.3do"); TacticsUse(0);
    bot.world=sithWorld_g_pCurrentWorld=&world; sithPlayer_g_pLocalPlayerThing=&self;
    bot.competitiveForce=bot.forceEnabled=1; bot.now=5; sithTime_g_secGameTime=10;
    own.aItems[SITHBIN_F_SPEED].amount=2; own.aItems[SITHBIN_F_SPEED].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_F_ABSORB].amount=4; own.aItems[SITHBIN_F_ABSORB].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_FORCEMANA].amount=100;
    #define SPEED_TRY() (bot.forceBin=-1, bot.nextForce=bot.nextSpeedProbe=0, memset(bot.keys,0,sizeof(bot.keys)), \
        memset(bot.axes,0,sizeof(bot.axes)), bot.axes[INPUT_FUNC_FORWARD]=1, Bot_TryMovementSpeed(&self), bot.forceBin==SITHBIN_F_SPEED)
    /* In a fight, with mana for Speed and two utility casts but not for
       Absorb on top: Speed goes up. The Absorb reserve used to forbid it. */
    bot.followingRoute=0;
    assert(SPEED_TRY());
    BT(SPEED_UPKEEP)=0; assert(!SPEED_TRY() && "the reserve held 260 mana back");
    own.aItems[SITHBIN_FORCEMANA].amount=300; assert(SPEED_TRY());
    /* On a walking leg whose next node is close: upkeep does not wait for a
       long straight; the old rule did. */
    bot.nNodes=1; bot.nodes[0].pos=(rdVector3){0.3f,0,BOT_FOOT_HEIGHT}; bot.nodes[0].sector=&plainLand;
    bot.route[0]=0; bot.routePos=0; bot.routeCount=1; bot.followingRoute=1; bot.routeMode=BOT_ROUTE_WALK;
    assert(!SPEED_TRY() && "old rule: the next node is too close");
    BT(SPEED_UPKEEP)=1; own.aItems[SITHBIN_FORCEMANA].amount=100; assert(SPEED_TRY());
    /* Jumps keep their own pace: a jump leg, or a running jump under way. */
    bot.routeMode=BOT_ROUTE_FORCEJUMP; assert(!SPEED_TRY());
    bot.routeMode=BOT_ROUTE_WALK; nav.runPhase=1; nav.runSeen=bot.now; assert(!SPEED_TRY());
    nav.runPhase=0; assert(SPEED_TRY());
    /* Still no cast once mana is short of the two utility casts. */
    own.aItems[SITHBIN_FORCEMANA].amount=59; assert(!SPEED_TRY());
    /* Near an opponent, where Grip takes hold, the Absorb reserve applies. */
    static SithThing near; static SithPlayer nearOwn;
    memset(&near,0,sizeof(near)); near.type=SITH_THING_PLAYER; near.sector=&plainLand;
    near.actorParams.pPlayer=&nearOwn; near.actorParams.health=100; near.position=(rdVector3){1.2f,0,BOT_FOOT_HEIGHT};
    jkPlayer_maxPlayers=2; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    jkPlayer_playerInfos[1].flags=1; jkPlayer_playerInfos[1].playerNetId=31; jkPlayer_playerInfos[1].pLocalPlayer=&near;
    bot.routeMode=BOT_ROUTE_WALK; own.aItems[SITHBIN_FORCEMANA].amount=100;
    assert(!SPEED_TRY() && "an opponent at 1.2: keep 200 for Absorb");
    near.position.x=3.0f; assert(SPEED_TRY() && "at 3.0: Speed");
    near.position.x=1.2f; own.aItems[SITHBIN_FORCEMANA].amount=260; assert(SPEED_TRY());
    jkPlayer_maxPlayers=0; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    #undef SPEED_TRY
    bot.followingRoute=0; bot.routeCount=bot.routePos=0; bot.nNodes=0; bot.forceBin=-1;
    bot.competitiveForce=0; testPlainActive=0;
    bot.world=sithWorld_g_pCurrentWorld=NULL; sithPlayer_g_pLocalPlayerThing=NULL;
    puts("PASS Speed kept up in fights and on short walking legs past the Absorb reserve, never on jumps, never below two utility casts");
}

static void test_fix_resupply(void)
{
    static SithSector land; static SithWorld world; static SithThing things[4];
    static rdModel3 concModel,pistolModel,fistsModel,rifleModel;
    SithThing self={0},armed={0},bare={0}; SithPlayer own={0},p1={0},p2={0};
    jkPlayerInfo armedInfo={0},bareInfo={0};
    memset(&land,0,sizeof(land)); memset(things,0,sizeof(things));
    strcpy(concModel.filename,"conp.3do"); strcpy(pistolModel.filename,"bryp.3do");
    strcpy(fistsModel.filename,"fistg.3do"); strcpy(rifleModel.filename,"strg.3do");
    jkBot_Configure("Resupply_Test","ky.3do"); TacticsUse(0); bot.elite=1; bot.now=5;
    self.type=SITH_THING_PLAYER; self.sector=&land; self.actorParams.pPlayer=&own; self.actorParams.health=100;
    PlainFace(&self,0);
    bot.world=sithWorld_g_pCurrentWorld=&world; world.aThings=things; world.numThings=3; world.numThingsLoaded=4;
    memset(nav.itemGuid,0,sizeof(nav.itemGuid));
    /* The stock pull makes a fresh +fpconcrifle where the victim stood. */
    SithThing *gun=&things[3];
    gun->type=SITH_THING_ITEM; gun->idx=3; gun->guid=900; gun->sector=&land;
    gun->collide=SITH_COLLIDE_SPHERE; gun->collideSize=0.04f; gun->renderData.model3=&concModel;
    strcpy(gun->aName,"+fpconcrifle"); gun->position=(rdVector3){1,0,0};
    assert(Bot_LooseWeapon(gun));
    gun->physicsParams.vel=(rdVector3){2,0,0}; assert(!Bot_LooseWeapon(gun) && "still flying to whoever pulled it");
    gun->physicsParams.vel=(rdVector3){0.1f,0,0}; assert(Bot_LooseWeapon(gun) && "sliding to a stop: fair game");
    gun->physicsParams.vel=(rdVector3){0,0,0};
    gun->collide=0; assert(!Bot_LooseWeapon(gun) && "not takeable for its first 0.2 s"); gun->collide=SITH_COLLIDE_SPHERE;
    nav.itemGuid[3]=900; assert(!Bot_LooseWeapon(gun) && "a level pickup is never loose"); nav.itemGuid[3]=0;
    gun->itemParams.flags=SITH_ITEM_BACKPACK; assert(!Bot_LooseWeapon(gun)); gun->itemParams.flags=0;
    gun->renderData.model3=&pistolModel; assert(!Bot_LooseWeapon(gun) && "the starting pistol"); gun->renderData.model3=&concModel;
    TacticsUse(1); assert(!Bot_LooseWeapon(gun) && !Bot_Transient(gun) && "legacy never looks for it"); TacticsUse(0);
    /* Worth what a missing concussion rifle is worth to an armed bot, and
       more to one out of shots. */
    own.aItems[SITHBIN_TUSKEN_PROD].amount=1; own.aItems[SITHBIN_TUSKEN_PROD].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_POWER].amount=40;
    assert(Bot_EquipmentValue(&self,3)==BT(VALUE_CONC));
    own.aItems[SITHBIN_TUSKEN_PROD].amount=0; own.aItems[SITHBIN_POWER].amount=0;
    assert(Bot_EquipmentValue(&self,3)==BT(VALUE_CONC)+4.0f);
    /* Out of shots: any real gun or its ammunition jumps the queue. */
    own.aItems[SITHBIN_REPEATER].amount=1; own.aItems[SITHBIN_REPEATER].state=SITHINVENTORY_ITEM_AVAILABLE;
    own.aItems[SITHBIN_POWER].amount=5;
    assert(Bot_Starved(&self));
    BotPickupKind rifle={BOT_ITEM_WEAPON,SITHBIN_STORMTROOPER_RIFLE,SITHBIN_ENERGY,500};
    assert(Bot_GunPickupValue(&self,rifle,1.0f)==12.0f && BT(VALUE_WEAPON)<12.0f);
    BotPickupKind conc={BOT_ITEM_WEAPON,SITHBIN_CONCUSSION_RIFLE,SITHBIN_POWER,500};
    assert(Bot_GunPickupValue(&self,conc,1.0f)==BT(VALUE_CONC)+4.0f && "raised alike, so the guns keep their order");
    /* A fresh choice is held for a moment, so ties at a waterline do not flip. */
    bot.armAt=bot.now-1.0f; assert(Bot_ArmHold()==1.5f);
    bot.armAt=bot.now-3.0f; assert(Bot_ArmHold()==1.15f);
    TacticsUse(1); bot.armAt=bot.now-1.0f; assert(Bot_ArmHold()==1.15f); TacticsUse(0);
    own.aItems[SITHBIN_POWER].amount=50; assert(!Bot_Starved(&self));
    assert(Bot_GunPickupValue(&self,rifle,1.0f)==BT(VALUE_WEAPON));
    /* An opponent left with fists is the easier kill: preferred over a nearer
       armed one, in targeting and in the hunt. */
    jkPlayer_maxPlayers=3; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    jkPlayer_playerInfos[1]=(SithPlayer){0}; jkPlayer_playerInfos[1].flags=1; jkPlayer_playerInfos[1].playerNetId=51;
    jkPlayer_playerInfos[1].pLocalPlayer=&armed;
    jkPlayer_playerInfos[2].flags=1; jkPlayer_playerInfos[2].playerNetId=52; jkPlayer_playerInfos[2].pLocalPlayer=&bare;
    armed.type=bare.type=SITH_THING_PLAYER; armed.sector=bare.sector=&land;
    armed.actorParams.health=bare.actorParams.health=100;
    armed.actorParams.pPlayer=&p1; bare.actorParams.pPlayer=&p2;
    armed.playerInfo=&armedInfo; bare.playerInfo=&bareInfo;
    armedInfo.rd_thing.model3=&rifleModel; bareInfo.rd_thing.model3=&fistsModel;
    armed.guid=61; bare.guid=62; armed.idx=6; bare.idx=7;
    armed.position=(rdVector3){2.0f,0,0}; bare.position=(rdVector3){3.0f,0,0};
    testLOS=1; bot.targetSlot=-1; bot.nextScan=0;
    assert(Bot_UpdateTarget(&self)==&bare && bot.targetSlot==2);
    TacticsUse(1); bot.targetSlot=-1; bot.nextScan=0;
    assert(Bot_UpdateTarget(&self)==&armed && bot.targetSlot==1 && "legacy takes the nearer");
    TacticsUse(0);
    /* No hunt while out of shots: resupply first. */
    bot.nNodes=2; WaterNode(0,0,&land,-1); WaterNode(1,2.5f,&land,-1);
    static flex_t distance[BOT_NODES]; distance[0]=0; distance[1]=2.5f;
    int slot=-1;
    assert(Bot_ElitePursuit(&self,0,distance,&slot)==1);
    own.aItems[SITHBIN_POWER].amount=5; assert(Bot_ElitePursuit(&self,0,distance,&slot)==-1);
    own.aItems[SITHBIN_POWER].amount=50;
    jkPlayer_maxPlayers=0; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    bot.nNodes=0; bot.targetSlot=-1; bot.world=sithWorld_g_pCurrentWorld=NULL;
    puts("PASS resupply: a pulled gun at rest is a pickup worth its kind, empty guns put ammunition first, disarmed opponents are preferred, no hunt without shots");
}

static void test_bot_tactic_fixes(void)
{
    jkPlayer_maxPlayers=0; memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    test_fix_respawn();
    test_fix_swim_thrust();
    test_fix_water_exit();
    test_fix_force_jump();
    test_fix_jump_memory();
    test_fix_speed();
    test_fix_resupply();
}
