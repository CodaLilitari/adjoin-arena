/* Extend Red's original driver fixture in the same translation unit so this
 * regression exercises the production Dijkstra, movement and cache code. */
#define main Red_OriginalTests
#include "test_bot_driver.c"
#undef main
HostServices *std_g_pHS;
int32_t sithNet_teamScore[5];

static const char *fixtureBytes;
static stdFile_t FixtureOpen(const char *name,const char *mode)
{
    (void)name; (void)mode;
    FILE *fp=tmpfile(); assert(fp);
    assert(fwrite(fixtureBytes,1,strlen(fixtureBytes),fp)==strlen(fixtureBytes)); rewind(fp);
    return (stdFile_t)(intptr_t)fp;
}
static int FixtureClose(stdFile_t h) { return fclose((FILE *)(intptr_t)h); }
static int FixtureSize(stdFile_t h) { (void)h; return (int)strlen(fixtureBytes); }
static size_t FixtureRead(stdFile_t h,void *buf,size_t n) { return fread(buf,1,n,(FILE *)(intptr_t)h); }

static void TransferFixture(const char *dir)
{
    static HostServices hs;
    static SithWorld world;
    static SithSector sector;
    static SithPlayer own;
    static SithThing self;
    hs.fileOpen=FixtureOpen; hs.fileRead=FixtureRead; hs.fileClose=FixtureClose; hs.fileSize=FixtureSize;
    std_g_pHS=&hs; setenv("ADJOIN_NAV_CACHE",dir,1);
    fixtureBytes="map A (four nodes)"; strcpy(world.map_jkl_fname,"same.jkl");
    memset(&nav,0,sizeof(nav)); memset(&bot,0,sizeof(bot));
    bot.world=&world; self.actorParams.pPlayer=&own; self.actorParams.health=100; self.sector=&sector;
    bot.nNodes=4; bot.followingRoute=1; bot.forceEnabled=0;
    for (int i=0;i<4;++i) {
        bot.nodes[i].sector=&sector; bot.nodes[i].pos=(rdVector3){i*0.25f,(i==2)*0.25f,0};
    }
    bot.nodes[0].edges[0]=(BotEdge){1,1,BOT_ROUTE_WALK}; bot.nodes[0].edges[1]=(BotEdge){2,1.4f,BOT_ROUTE_WALK};
    bot.nodes[1].edges[0]=(BotEdge){3,1,BOT_ROUTE_WALK}; bot.nodes[2].edges[0]=(BotEdge){3,1.4f,BOT_ROUTE_WALK};
    bot.nodes[0].nEdges=2; bot.nodes[1].nEdges=bot.nodes[2].nEdges=1;
    sithNet_MultiModeFlags=0; Transfer_Context(&self,1);
    assert(transfer.recall.lock>=0 && transfer.recall.loaded==0 && strlen(transfer.map)==64);
    char mapA[65]; strcpy(mapA,transfer.map);
    flex_t distance[BOT_NODES]; int parent[BOT_NODES];
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==1 && distance[3]==2);
    assert(Bot_SetRoute(0,3,parent));
    bot.frameDt=0.034f; bot.stuckAt=bot.now=1;
    for (int i=0; i<70 && !transfer.failures; ++i) {
        bot.now+=bot.frameDt; Bot_Recovery(&self);
    }
    assert(transfer.failures==1 && bot.nextRecovery>bot.now);
    /* Let ordinary transient avoids expire before comparing Dijkstra paths. */
    bot.now+=10; bot.nextRecovery=0;
    assert(Transfer_Cost(0,1,BOT_ROUTE_WALK,1)==2 && Transfer_Cost(1,0,BOT_ROUTE_WALK,1)==0);
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==2 && distance[3]>2.79f && distance[3]<2.81f);
    Transfer_Context(&self,1); assert(transfer.recall.loaded==1 && Transfer_Cost(0,1,BOT_ROUTE_WALK,1)==2);
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==2);
    fixtureBytes="map B, same display name"; Transfer_Context(&self,1);
    assert(strcmp(mapA,transfer.map) && !transfer.recall.loaded);
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==1);
    fixtureBytes="map A (four nodes)"; sithNet_MultiModeFlags=MULTIMODEFLAG_TEAMS|MULTIMODEFLAG_100;
    Transfer_Context(&self,1); assert(!transfer.recall.loaded && !strcmp(transfer.scope,"tdm/guns/noforce"));
    nav.ctf=1; Transfer_Context(&self,0); assert(!strcmp(transfer.scope,"ctf/guns/noforce"));
    assert(!Transfer_Match(transfer.scope,transfer.map,transfer.scope,transfer.map));
    nav.ctf=0; sithNet_MultiModeFlags=0; bot.sabersOnly=1; Transfer_Context(&self,0);
    assert(!Transfer_Match(transfer.scope,transfer.map,transfer.scope,transfer.map));
    bot.sabersOnly=0; Transfer_Context(&self,0);
    assert(Transfer_Match(transfer.scope,transfer.map,"ffa/guns/noforce",mapA));
    assert(!Transfer_Match(transfer.scope,transfer.map,"tdm/guns/noforce",mapA));
    assert(!Transfer_Match(transfer.scope,transfer.map,"ffa/guns/noforce","wrong-map"));
    assert(transfer.recall.loaded==1);
    assert(Bot_SetRoute(0,1,parent)); bot.nextPlan=bot.now+10;
    self.position=bot.nodes[1].pos; Bot_Navigate(&self);
    assert(transfer.arrivals==1 && Transfer_Cost(0,1,BOT_ROUTE_WALK,1)==0);
    bot.now+=4; /* Red briefly avoids the very waypoint just reached. */
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==1);
    NavEdgeRecord r={1,2,100,0,4};
    assert(NR_Level(r,100)==4 && NR_Level(r,100+NR_DECAY)==3 && !NR_Level(r,100+NR_AGE));
    /* BrainStore edge prior: a frozen model that distrusts short edges must
     * flip the planner to the 0-2-3 route, and removing it must restore the
     * shipped choice. No prior is the default everywhere above. */
    {
        char modelPath[512],hex[65]; unsigned char hash[32];
        const char *model="ADJOIN_EDGE_V1 10\n"
            "0 0 0 0 0 0 0 0 0 0\n1 1 1 1 1 1 1 1 1 1\n"
            "20 0 0 0 0 0 0 0 0 0\n-5\n";
        assert(snprintf(modelPath,sizeof(modelPath),"%s/edge-model.txt",dir)>0);
        FILE *mf=fopen(modelPath,"wb"); assert(mf);
        assert(fwrite(model,1,strlen(model),mf)==strlen(model)); fclose(mf);
        assert(SHA256((unsigned char*)model,strlen(model),hash));
        for (int i=0;i<32;i++) snprintf(hex+2*i,3,"%02x",hash[i]);
        setenv("ADJOIN_EDGE_MODEL",modelPath,1); setenv("ADJOIN_EDGE_MODEL_SHA256",hex,1);
        Transfer_Context(&self,1); assert(transfer.edgeLoaded);
        assert(Transfer_Cost(0,1,BOT_ROUTE_WALK,1)>1.9f && Transfer_Cost(0,1,BOT_ROUTE_WALK,1)<2.1f);
        Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==2);
        setenv("ADJOIN_EDGE_MODEL","",1); setenv("ADJOIN_EDGE_MODEL_SHA256","",1);
        Transfer_Context(&self,1); assert(!transfer.edgeLoaded);
        Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==1);
        puts("PASS BrainStore edge prior flips Dijkstra route and removal restores it");
    }
    puts("PASS native Dijkstra route 0-1-3 -> 0-2-3 after genuine routed stall callback; "
         "reopened map retains evidence, other bytes and TDM isolated, CTF/saber model protection, success/expiry recovery");
}

#ifdef JKBOT_TEST_PLATFORM
static void PlatformFixture(void)
{
    (void)Custom_Admission;
    SithWorld world={0}; SithThing self={0};
    memset(&bot,0,sizeof(bot)); bot.world=&world; world.aThings=testBridgeThings;
    testBridgeActive=1;
    for (int i=0;i<2;i++) {
        testBridgeSectors[i]=(SithSector){0};testBridgeSectors[i].id=i;
        testBridgeThings[i]=(SithThing){0};testBridgeThings[i].sector=&testBridgeSectors[i];
        testBridgeThings[i].type=SITH_THING_COG;testBridgeThings[i].collide=SITH_COLLIDE_FACE;
        testBridgeThings[i].flags=SITH_TF_STANDABLE;
    }
    self.sector=&testBridgeSectors[1];self.sector->flags=SITH_SECTOR_FALLDEATH;
    self.moveSize=self.collideSize=0.045f;
    self.position=(rdVector3){39.475f,6,28.599879f+BOT_FOOT_HEIGHT};
    rdVector3 ahead,along={0,1,0},off={1,0,0};int fixture=-1,probes=0,rejects=0;
    assert(Platform_Step(&self,along,&ahead,&fixture,&probes,&rejects));
    assert(fixture==1 && probes>=15 && !rejects && ahead.y>self.position.y+0.20f);
    assert(!Platform_Step(&self,off,&ahead,&fixture,&probes,&rejects) && rejects);
    SithSector *floor=NULL;rdVector3 high=self.position;high.z+=0.04f;
    assert(!Bot_Floor(high,self.sector,0.3f,&ahead,&floor)); /* ordinary graph keeps its pit guard */
    testBridgeThings[1].flags=0;
    assert(!Platform_Step(&self,along,&ahead,&fixture,&probes,&rejects));
    testBridgeThings[1].flags=SITH_TF_STANDABLE;testBridgeThings[1].moveType=SITH_MT_PATH;
    testBridgeThings[1].trackParams.loadedFrames=2;
    assert(!Platform_Step(&self,along,&ahead,&fixture,&probes,&rejects));
    testBridgeThings[1].trackParams.loadedFrames=0;self.sector->flags|=SITH_SECTOR_NOACTORENTER;
    assert(!Platform_Step(&self,along,&ahead,&fixture,&probes,&rejects));
    assert(queryDepth==0);testBridgeActive=0;
    puts("PASS supported platform step, bridge side void, unstandable/moving fixture, prohibited sector and ordinary graph guard");
}
#endif

#ifdef JKBOT_TEST_HINT
static void HintFixture(const char *dir)
{
    SithWorld world={0};SithSector sectors[2]={{0}};SithThing fixtures[2]={{0}};
    sectors[0].id=0;sectors[1].id=1;sectors[0].flags=SITH_SECTOR_FALLDEATH;
    world.numSectors=2;world.numThings=2;world.aThings=fixtures;bot.world=&world;
    fixtures[0].type=SITH_THING_COG;fixtures[0].collide=SITH_COLLIDE_FACE;
    fixtures[0].sector=&sectors[0];fixtures[0].flags=SITH_TF_STANDABLE;
    char path[512],data[512],hex[65];unsigned char hash[32];
    assert(snprintf(path,sizeof(path),"%s/route",dir)>0);
    memset(transfer.map,'a',64);transfer.map[64]=0;
    snprintf(data,sizeof(data),"RED_ROUTE_HINT_V1 %s 3\n0 0 0 0 130\n0 0 0 400 130\n1 -1 0 600 120\n",transfer.map);
    assert(SHA256((unsigned char*)data,strlen(data),hash));
    for (int i=0;i<32;i++) snprintf(hex+2*i,3,"%02x",hash[i]);
    FILE *file=fopen(path,"wb");assert(file);assert(fwrite(data,1,strlen(data),file)==strlen(data));fclose(file);
    memset(&hint,0,sizeof(hint));assert(Hint_Read(path,hex) && hint.count==3);
    memset(&hint,0,sizeof(hint));hex[0]=hex[0]=='a'?'b':'a';assert(!Hint_Read(path,hex) && !hint.count);
    snprintf(hex,3,"%02x",hash[0]);for (int i=1;i<32;i++) snprintf(hex+2*i,3,"%02x",hash[i]);
    transfer.map[0]='b';assert(!Hint_Read(path,hex));transfer.map[0]='a';
    fixtures[0].flags=0;assert(!Hint_Read(path,hex));fixtures[0].flags=SITH_TF_STANDABLE;
    fixtures[0].sector=&sectors[1];assert(!Hint_Read(path,hex));
    char bad[1024];int count=0;
    snprintf(bad,sizeof(bad),"RED_ROUTE_HINT_V1 %s 2\n0 0 0 0 0\n1 -1 0 3100 0\n",transfer.map);
    assert(!Hint_Parse(bad,transfer.map,hint.points,&count));
    snprintf(bad,sizeof(bad),"%s garbage",data);assert(!Hint_Parse(bad,transfer.map,hint.points,&count));
    puts("PASS map-scoped hint artifact, changed JKL, wrong digest/support/sector, discontinuous route and trailing input");
}
#endif

int main(int argc,char **argv)
{
    assert(argc==2);
    int rc=Red_OriginalTests(); if (rc) return rc;
    TransferFixture(argv[1]);
#ifdef JKBOT_TEST_PLATFORM
    PlatformFixture();
#endif
#ifdef JKBOT_TEST_HINT
    HintFixture(argv[1]);
#endif
    return 0;
}
