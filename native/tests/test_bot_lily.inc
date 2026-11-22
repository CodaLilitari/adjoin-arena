/* Socket ingress and ordinary game input getters share the production tick. */
static void motor(uint32_t seq,uint32_t sample,int duration,int buttons,double expiry)
{
    command(20,seq,26,expiry);
    setword(frame+28,sample); setword(frame+32,11);
    frame[36]=1; frame[37]=duration; frame[38]=duration>>8;
    frame[39]=75; frame[40]=(unsigned char)-50; frame[41]=30; frame[42]=10;
    frame[43]=buttons;
}
static void testLily(void)
{
    setenv("JK_BOT_LILY","1",1);
    jkBot_Configure("Lily","ky.3do"); jkBot_OnJoined(); tick();
    assert(receive(7)>=128);
    epoch=word(frame+8); life=word(frame+12);
    uint32_t sample=word(frame+20);
    motor(1,sample,95,1,clockseconds()-1); submit(46); ack(20,CP_EXPIRED,1);
    motor(2,sample,95,1,clockseconds()+2); frame[39]=110; submit(46); ack(20,CP_REJECTED,2);
    motor(3,sample+99,95,1,clockseconds()+2); submit(46); ack(20,CP_STALE,3);
    motor(4,sample,95,1,clockseconds()+2); submit(46); ack(20,CP_APPLIED,4);
    int pressed;
    assert(jkBot_GetKey(INPUT_FUNC_JUMP,&pressed) && pressed==1);
    assert(jkBot_GetAxis(INPUT_FUNC_FORWARD)==0.75f && jkBot_GetAxis(INPUT_FUNC_SLIDE)==-0.5f);
    motor(5,sample,66,1,clockseconds()+2); submit(46); ack(20,CP_APPLIED,5);
    motor(6,sample,33,1,clockseconds()+2); submit(46); ack(20,CP_REJECTED,6);
    tick(); assert(jkBot_GetKey(INPUT_FUNC_JUMP,&pressed) && !pressed);
    for (int i=0;i<5;i++) tick();
    companion.nextState=0; tick(); /* dropped original terminal must be recoverable */
    int replay=0;
    while(receive(6)) {
        if(word(frame+20)==5 && frame[33]==4 && frame[35]==2 && word(frame+36)>=66) replay=1;
    }
    assert(replay);
    /* One active maneuver owns the route until the physical pose reaches
       the offered node. Move only the fixture's observed pose between ticks. */
    self.attach_flags=SITH_ATTACH_SURFACE;
    bot.nNodes=3; bot.graphDone=1; bot.goal=-1;
    for (int i=0;i<3;i++) {
        bot.nodes[i]=(BotNode){.pos={0.4f*i,0,0},.sector=&sector,.item=-1};
        if (i<2) { bot.nodes[i].nEdges=1; bot.nodes[i].edges[0]=(BotEdge){i+1,0.4f,0}; }
    }
    lily.offeredAt-=2; companion.nextState=0; tick();
    assert(receive(5)==89 && frame[28]==2);
    sample=word(frame+20); uint32_t offer=word(frame+24);
    command(19,7,24,clockseconds()+2); setword(frame+28,sample); setword(frame+32,11);
    setword(frame+36,offer); setword(frame+40,2); submit(44); ack(19,CP_APPLIED,7);
    assert(bot.goal==2 && bot.routePos==0 && bot.routeCount==2);
    self.position=bot.nodes[1].pos; bot.nextPlan=0; tick();
    assert(bot.goal==2 && bot.routePos==1 && "routine planning preserved committed cursor");
    assert(lily.active.seq==7);
    self.position=bot.nodes[2].pos; tick();
    int arrived=0;
    while (receive(6)) if (word(frame+20)==7 && frame[33]==4 && frame[35]==1) arrived=1;
    assert(arrived);
    assert(!lily.active.seq && bot.goal==-1);

    /* Both button classes, both view axes, ordinary inventory keys, and hot
       behavior settings apply on the same native control frame. */
    self.actorParams.pPlayer->curWeaponID=2;
    self.actorParams.pPlayer->aItems[21].state=SITHINVENTORY_ITEM_AVAILABLE;
    self.actorParams.pPlayer->aItems[21].amount=2;
    self.actorParams.pPlayer->aItems[SITHBIN_FORCEMANA].amount=200;
    bot.forceEnabled=1; bot.sabersOnly=0;
    motor(8,sample,400,31,clockseconds()+2); frame[44]=3; frame[45]=21;
    submit(46); ack(20,CP_APPLIED,8);
    assert(jkBot_GetKey(INPUT_FUNC_SELECT1+2,NULL) && jkBot_GetKey(Bot_PowerKey(21),NULL));
    assert(jkBot_GetAxis(INPUT_FUNC_TURN)==0.3f && jkBot_GetAxis(INPUT_FUNC_PITCH)==0.1f);
    assert(jkBot_GetKey(INPUT_FUNC_FIRE1,NULL) && jkBot_GetKey(INPUT_FUNC_FIRE2,NULL));
    bot.forceEnabled=0; bot.sabersOnly=1; tick();
    assert(!jkBot_GetKey(INPUT_FUNC_FIRE1,NULL) && !jkBot_GetKey(Bot_PowerKey(21),NULL));
    assert(!jkBot_GetKey(INPUT_FUNC_SELECT1+2,NULL));
    command(18,9,8,clockseconds()+2); submit(28); ack(18,CP_APPLIED,9);
    assert(!jkBot_GetKey(INPUT_FUNC_JUMP,NULL));
    bot.forceEnabled=1; bot.sabersOnly=0;
    nav.jumpUntil=bot.now+0.2f; nav.jumpStarted=bot.now;
    motor(10,sample,66,1,clockseconds()+2); submit(46); ack(20,CP_APPLIED,10);
    assert(!lily.active.seq && lily.queued.seq==10);
    nav.jumpUntil=0; tick(); assert(lily.active.seq==10);
    self.signature++; tick(); assert(!lily.active.seq && !lily.queued.seq);
    assert(receive(6)==44);
    epoch=companion.world; life=companion.life;
    companion.nextState=0; tick(); sample=lily.sample;
    SithThing peaceful={.type=SITH_THING_PLAYER,.sector=&sector,.guid=90,.position=self.position};
    peaceful.position.y+=0.25f;
    jkPlayer_playerInfos[1].pLocalPlayer=&peaceful;
    self.orient.lvec=(rdVector3){0,1,0}; self.orient.uvec=(rdVector3){0,0,1};
    BotPeer *observed=Bot_Peer(1); assert(observed);
    observed->seenWeapon=1; observed->weapon=SITHBIN_FISTS;
    bot.fistsPeace=1;
    assert(Bot_ProtectedPlayer(&self,1));
    motor(11,sample,1,8,clockseconds()+2); submit(46); ack(20,CP_APPLIED,11);
    assert(!jkBot_GetKey(INPUT_FUNC_FIRE1,NULL));
    jkPlayer_playerInfos[1].pLocalPlayer=NULL;
    tick();
    unsigned char duplicate[46];
    for (int i=12;i<312;i++) {
        motor(i,lily.sample,1,0,clockseconds()+2);
        if (i==311) memcpy(duplicate,frame,sizeof(duplicate));
        submit(46); ack(20,CP_APPLIED,i); tick();
    }
    assert(!lily.active.seq && !lily.queued.seq);
    memcpy(frame,duplicate,sizeof(duplicate)); submit(46); ack(20,CP_APPLIED,311);
    assert(!lily.active.seq && !lily.queued.seq);
    motor(20,lily.sample,1,0,clockseconds()+2); submit(46); ack(20,CP_STALE,20);
    lily.samples[lily.sample%32].time-=2;
    motor(312,lily.sample,1,0,clockseconds()+2); submit(46); ack(20,CP_STALE,312);
    puts("PASS 300 native actions, exact replay, evicted sequence fence, aged sample and fists-peace");
    puts("PASS committed cursor, physical route arrival, stock fire/weapon/Force inputs, atomic admission and lifecycle release");
    puts("PASS native Lily bounded chunks, stale/expiry validation, actual axes, held edges and terminal identity");
}
