/* Controlled flat floor, optional cross-wall, and ordinary template inheritance. */
static int testCombatArena, testCombatWall;
static SithThing testConcProjectile, testRailProjectile, testConcBlast, testRailBlast;

static int TestCombatCollision(SithSector *sector,const rdVector3 *from,const rdVector3 *dir,
                              flex_t length,flex_t radius,SithCollision *hit)
{
    flex_t at=length+1;
    if (dir->z<0) at=(from->z-radius)/-dir->z;
    if (testCombatWall && dir->y>0 && from->y<0.5f) {
        flex_t wallAt=(0.5f-from->y-radius)/dir->y;
        if (testCombatWall==1 || from->z+wallAt*dir->z-radius<0.105f)
            at=Bot_Min(at,wallAt);
    }
    if (at<0 || at>length) return 0;
    *hit=(SithCollision){0}; hit->type=SITHCOLLISION_WORLD; hit->distance=at;
    corridorFloor.pSector=sector;
    corridorFloor.flags=SITH_SURFACE_HAS_COLLISION|SITH_SURFACE_FLOOR;
    hit->surface=&corridorFloor; hit->hitNorm.z=1;
    return 1;
}

static void test_bot_gunshots(void)
{
    SithThing self={0}, enemy={0}, ally={0};
    SithSector sector={0};
    jkBot_Configure("Bot_Aim","ky.3do");
    bot.elite=1; bot.fistsPeace=0; bot.now=1; bot.targetSlot=1;
    testCombatArena=1; fixtureMode=corridorMode=testSlopeActive=testBridgeActive=testC1Active=0;
    memset(jkPlayer_playerInfos,0,sizeof(jkPlayer_playerInfos));
    jkPlayer_maxPlayers=3; sithNet_MultiModeFlags=MULTIMODEFLAG_TEAMS;
    SithThing *players[]={&self,&enemy,&ally};
    for (int i=0;i<3;i++) {
        SithPlayer *p=&jkPlayer_playerInfos[i];
        p->pLocalPlayer=players[i]; p->flags=1; p->teamNum=i==1 ? 2 : 1; p->playerNetId=i+1;
        players[i]->type=SITH_THING_PLAYER; players[i]->sector=&sector;
        players[i]->actorParams.pPlayer=p; players[i]->position.z=BOT_FOOT_HEIGHT;
        players[i]->collideSize=players[i]->moveSize=.065f;
    }
    ally.position.x=9; enemy.position.y=2; enemy.physicsParams.vel.x=1;
    testConcBlast.type=testRailBlast.type=SITH_THING_EXPLOSION;
    testConcBlast.explosionParams.range=.8f; testRailBlast.explosionParams.range=.5f;
    testConcProjectile.weaponParams.pExplosionTemplate=testConcProjectile.weaponParams.fleshHitTemplate=&testConcBlast;
    testRailProjectile.weaponParams.pExplosionTemplate=testRailProjectile.weaponParams.fleshHitTemplate=&testRailBlast;
    testConcProjectile.physicsParams.vel.y=7; testRailProjectile.physicsParams.vel.y=2.5f;
    testConcProjectile.moveSize=.005f; testRailProjectile.moveSize=.003f;
    BotGunShot shot=Bot_PlanGunShot(&self,&enemy,SITHBIN_CONCUSSION_RIFLE);
    assert(shot.aim.x>.24f && shot.aim.x<.34f && shot.aim.z>0 && shot.aim.z<.025f);
    assert(Bot_GunSafe(&self,&enemy,&shot,0));
    assert(!Bot_FloorAimAligned(&self,&shot)); /* Horizontal barrel would sail over this floor. */
    rdVector3 line=Bot_Sub(shot.aim,self.position);
    self.actorParams.headPYR.x=atan2f(line.z,Bot_Horizontal(line))*BOT_DEG;
    assert(Bot_FloorAimAligned(&self,&shot));
    self.actorParams.pPlayer->aItems[SITHBIN_CONCUSSION_RIFLE].amount=1;
    self.actorParams.pPlayer->aItems[SITHBIN_CONCUSSION_RIFLE].state=SITHINVENTORY_ITEM_AVAILABLE;
    self.actorParams.pPlayer->aItems[SITHBIN_POWER].amount=8;
    Bot_SelectWeapon(&self,2); assert(bot.keys[INPUT_FUNC_SELECT1+SITHBIN_CONCUSSION_RIFLE-1]);
    ally.position=shot.aim; ally.position.x+=.76f; assert(!Bot_GunSafe(&self,&enemy,&shot,0));
    ally.position=(rdVector3){1.55f,2,BOT_FOOT_HEIGHT};
    ally.physicsParams.vel.x=1;
    assert(Bot_GunSafe(&self,&enemy,&shot,0)); /* Moving away from impact. */
    ally.physicsParams.vel.x=-2;
    assert(!Bot_GunSafe(&self,&enemy,&shot,0)); /* Moving into the splash. */
    ally.physicsParams.vel.x=0; ally.position.x=9; testCombatWall=2;
    BotGunShot overLip=Bot_PlanGunShot(&self,&enemy,SITHBIN_CONCUSSION_RIFLE);
    assert(!overLip.floorAim && overLip.aim.z==enemy.position.z && Bot_GunSafe(&self,&enemy,&overLip,0));
    testCombatWall=1; assert(!Bot_GunSafe(&self,&enemy,&shot,0)); testCombatWall=0;
    enemy.position.z=1.1f;
    shot=Bot_PlanGunShot(&self,&enemy,SITHBIN_CONCUSSION_RIFLE);
    assert(shot.aim.z>.95f);
    enemy.position.z=BOT_FOOT_HEIGHT; enemy.physicsParams.vel.x=0; enemy.position.y=.76f;
    shot=Bot_PlanGunShot(&self,&enemy,SITHBIN_CONCUSSION_RIFLE); assert(!Bot_GunSafe(&self,&enemy,&shot,0));
    shot=Bot_PlanGunShot(&self,&enemy,SITHBIN_RAIL_DETONATOR); assert(Bot_GunSafe(&self,&enemy,&shot,0));
    testRailBlast.explosionParams.range=1.2f;
    shot=Bot_PlanGunShot(&self,&enemy,SITHBIN_RAIL_DETONATOR); assert(!Bot_GunSafe(&self,&enemy,&shot,0));
    testRailProjectile.weaponParams.pExplosionTemplate=NULL;
    shot=Bot_PlanGunShot(&self,&enemy,SITHBIN_RAIL_DETONATOR); assert(!Bot_GunSafe(&self,&enemy,&shot,0));
    testCombatArena=0; sithNet_MultiModeFlags=0; assert(queryDepth==0);
    puts("PASS predicted concussion floor/direct aim, legal selection, template splash, friendly/self and wall rejection");
}
