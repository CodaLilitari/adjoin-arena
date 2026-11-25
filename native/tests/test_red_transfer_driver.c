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
    assert(Transfer_Cost(0,1,BOT_ROUTE_WALK)==2 && Transfer_Cost(1,0,BOT_ROUTE_WALK)==0);
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==2 && distance[3]>2.79f && distance[3]<2.81f);
    Transfer_Context(&self,1); assert(transfer.recall.loaded==1 && Transfer_Cost(0,1,BOT_ROUTE_WALK)==2);
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
    assert(transfer.arrivals==1 && Transfer_Cost(0,1,BOT_ROUTE_WALK)==0);
    bot.now+=4; /* Red briefly avoids the very waypoint just reached. */
    Bot_SearchPaths(&self,0,distance,parent,0); assert(parent[3]==1);
    NavEdgeRecord r={1,2,100,0,4};
    assert(NR_Level(r,100)==4 && NR_Level(r,100+NR_DECAY)==3 && !NR_Level(r,100+NR_AGE));
    puts("PASS native Dijkstra route 0-1-3 -> 0-2-3 after genuine routed stall callback; "
         "reopened map retains evidence, other bytes and TDM isolated, CTF/saber model protection, success/expiry recovery");
}

int main(int argc,char **argv)
{
    assert(argc==2);
    int rc=Red_OriginalTests(); if (rc) return rc;
    TransferFixture(argv[1]); return 0;
}
