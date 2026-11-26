/* Run the ordinary fight dispatcher, including the stock-input safety checks.
   The collision adapter supplies a flat floor and an optional narrow mesh. */
static void TestSaberFrame(SithThing *self,SithThing *enemy)
{
    memset(bot.axes,0,sizeof(bot.axes)); memset(bot.keys,0,sizeof(bot.keys));
    bot.rawTurn=bot.rawPitch=0;
    bot.now+=bot.frameDt;
    Bot_Combat(self,enemy);
}

static void test_bot_saber_tracking(FILE *frames)
{
    SithThing self={0},enemy={0};
    SithSector sector={0}; rdModel3 model={0};
    testCombatArena=testLOS=1; testCombatWall=testPlainActive=0;
    sithNet_MultiModeFlags=0; jkPlayer_maxPlayers=2;
    memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    SithThing *players[]={&self,&enemy};
    for (int i=0;i<2;i++) {
        SithThing *p=players[i];
        p->type=SITH_THING_PLAYER; p->sector=&sector; p->actorParams.health=100;
        p->position.z=BOT_FOOT_HEIGHT; p->moveSize=p->collideSize=0.065f;
        p->collide=SITH_COLLIDE_SPHERE; p->attach_flags=SITH_ATTACH_SURFACE;
        p->orient.lvec.y=1; p->orient.rvec.x=1; p->actorParams.maxRotVelocity=200;
        p->actorParams.pPlayer=&jkPlayer_playerInfos[i];
        jkPlayer_playerInfos[i].pLocalPlayer=p; jkPlayer_playerInfos[i].flags=1;
        jkPlayer_playerInfos[i].playerNetId=i+1;
    }
    SithPlayer *p=self.actorParams.pPlayer;
    p->aItems[SITHBIN_LIGHTSABER].state=SITHINVENTORY_ITEM_AVAILABLE;
    p->aItems[SITHBIN_LIGHTSABER].amount=1; p->curWeaponID=SITHBIN_LIGHTSABER;
    enemy.position.y=.14f;
    /* Set the two production configurations and observe ten consecutive
       frames during which the attack input is held. */
    for (int tracked=0;tracked<=1;tracked++) {
        if (tracked) unsetenv("JK_BOT_SABER_TRACK");
        else setenv("JK_BOT_SABER_TRACK","0",1);
        jkBot_Configure("Saber","ky.3do");
        TacticsUse(0);
        bot.now=1; bot.sabersOnly=1; bot.forceEnabled=0; bot.targetSlot=1;
        bot.frameDt=.02f; bot.strafeSide=1; bot.strafeUntil=100;
        for (int tick=0;tick<10;tick++) {
            TestSaberFrame(&self,&enemy);
            assert(bot.keys[INPUT_FUNC_FIRE1] || bot.keys[INPUT_FUNC_FIRE2]);
            assert((fabsf(bot.axes[INPUT_FUNC_SLIDE])>.6f)==tracked);
            assert(fabsf(bot.axes[INPUT_FUNC_FORWARD])<.01f);
            if (frames) fprintf(frames,"%d %d %.9g %.9g %d %d %d\n",
                tracked,tick,(double)jkBot_GetAxis(INPUT_FUNC_SLIDE),(double)jkBot_GetAxis(INPUT_FUNC_FORWARD),
                !!jkBot_GetKey(INPUT_FUNC_FIRE1,NULL),!!jkBot_GetKey(INPUT_FUNC_FIRE2,NULL),
                !!jkBot_GetKey(INPUT_FUNC_FAST,NULL));
            memcpy(bot.previous,bot.keys,sizeof(bot.previous));
        }
    }
    /* Offset the collision geometry while keeping the same origin as an
       ordinary standing target. The same visible skin with a sphere still
       uses the true sphere centre. */
    enemy.renderData.model3=&model; enemy.collide=SITH_COLLIDE_FACE;
    saberBandTarget=&enemy;
    for (int sign=-1;sign<=1;sign+=2) {
        saberBandZ=enemy.position.z+sign*enemy.collideSize*.45f;
        TestSaberFrame(&self,&enemy);
        assert(sign*(bot.rawPitch+bot.axes[INPUT_FUNC_PITCH])>0);
        assert(fabsf(bot.axes[INPUT_FUNC_SLIDE])>.6f);
    }
    enemy.collide=SITH_COLLIDE_SPHERE;
    TestSaberFrame(&self,&enemy);
    assert(bot.rawPitch==0 && bot.axes[INPUT_FUNC_PITCH]==0);
    saberBandTarget=NULL;
    /* A rising or falling target is led; a simultaneous equal jump has
       zero relative lead. A target directly above still requests pitch. */
    for (int sign=-1;sign<=1;sign+=2) {
        enemy.physicsParams.vel.z=sign*.6f;
        TestSaberFrame(&self,&enemy);
        assert(sign*(bot.rawPitch+bot.axes[INPUT_FUNC_PITCH])>0);
    }
    self.physicsParams.vel.z=enemy.physicsParams.vel.z;
    TestSaberFrame(&self,&enemy);
    assert(bot.rawPitch==0 && bot.axes[INPUT_FUNC_PITCH]==0);
    enemy.position.y=0; enemy.position.z+=.18f;
    TestSaberFrame(&self,&enemy);
    assert(bot.rawPitch+bot.axes[INPUT_FUNC_PITCH]>0);
    /* Neither tangent has floor. Preserve the movement veto at a drop. */
    testCombatArena=0; self.attach_flags=0;
    enemy.position.y=.14f; enemy.position.z=self.position.z;
    TestSaberFrame(&self,&enemy);
    assert(!bot.axes[INPUT_FUNC_FORWARD] && !bot.axes[INPUT_FUNC_SLIDE]);
    assert(queryDepth==0);
    memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos)); jkPlayer_maxPlayers=0;
    puts("PASS saber contact: 10/10 attacking frames with strafe (legacy 0/10); lower/upper mesh bands, sphere centre, rise/fall, overhead pitch and drop veto");
}
