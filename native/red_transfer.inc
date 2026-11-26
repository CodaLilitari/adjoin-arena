/* Included after Red's CTF bindings and before his normal graph search. */
#include "red_nav_recall.h"
#include "General/stdFnames.h"
#include <openssl/evp.h>

static struct {
    SithWorld *world; char map[65],scope[48];
    int flags,rank,applies,trace,routeStart,initialized,searchLogged,navCount;
    unsigned failures,arrivals; flex_t nextState,nextExploreLog;
    uint64_t keys[BOT_NODES]; int bucket[256],next[NR_LIMIT];
    NavRecall recall;
    long wall;
    /* Optional BrainStore global edge prior (ADJOIN_EDGE_MODEL[_SHA256]). */
    int edgeLoaded;
    float edgeCenter[10],edgeScale[10],edgeWeight[10],edgeBias;
    char edgeDigest[65];
} transfer;

/* Load a frozen ADJOIN_EDGE_V1 artifact exported by bots.brain. Both the
 * path and its expected SHA-256 must be supplied; any defect leaves the
 * prior disabled and planning exactly as before. */
static int Transfer_LoadEdgeModel(void)
{
    transfer.edgeLoaded=0; transfer.edgeDigest[0]=0;
    const char *path=getenv("ADJOIN_EDGE_MODEL"),*expected=getenv("ADJOIN_EDGE_MODEL_SHA256");
    if (!path || !expected || strlen(expected)!=64) return 0;
    FILE *file=fopen(path,"rb");
    if (!file) return 0;
    char bytes[8193];
    size_t n=fread(bytes,1,sizeof(bytes),file);
    int ok=n>0 && n<sizeof(bytes) && !ferror(file) && feof(file) && !memchr(bytes,0,n);
    fclose(file);
    if (!ok) return 0;
    unsigned char hash[32]; unsigned size=0;
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();
    ok=ctx && EVP_DigestInit_ex(ctx,EVP_sha256(),NULL) && EVP_DigestUpdate(ctx,bytes,n) &&
        EVP_DigestFinal_ex(ctx,hash,&size) && size==32;
    if (ctx) EVP_MD_CTX_free(ctx);
    if (!ok) return 0;
    for (int i=0;i<32;++i) snprintf(transfer.edgeDigest+2*i,3,"%02x",hash[i]);
    if (strcmp(transfer.edgeDigest,expected)) { transfer.edgeDigest[0]=0; return 0; }
    bytes[n]=0;
    const char *header="ADJOIN_EDGE_V1";
    size_t hlen=strlen(header);
    if (strncmp(bytes,header,hlen) || !isspace((unsigned char)bytes[hlen])) return 0;
    char *cursor=bytes+hlen,*end=NULL;
    long count=strtol(cursor,&end,10);
    if (end==cursor || count!=10) return 0;
    cursor=end;
    float *fields[3]={transfer.edgeCenter,transfer.edgeScale,transfer.edgeWeight};
    for (int group=0;group<3;++group) for (int i=0;i<10;++i) {
        double value=strtod(cursor,&end);
        if (end==cursor || !isfinite(value) || (group==1 && value<=0)) return 0;
        fields[group][i]=(float)value; cursor=end;
    }
    double bias=strtod(cursor,&end);
    if (end==cursor || !isfinite(bias)) return 0;
    cursor=end;
    while (isspace((unsigned char)*cursor)) ++cursor;
    if (*cursor) return 0;
    transfer.edgeBias=(float)bias;
    transfer.edgeLoaded=1;
    if (transfer.trace) {
        fprintf(stderr,"BOT_EDGE_MODEL name=%s sha256=%s status=loaded\n",bot.name,transfer.edgeDigest);
        fflush(stderr);
    }
    return 1;
}

/* Predicted-failure surcharge in graph cost units, capped so a prior can
 * reorder legal routes but never create or forbid one. */
static flex_t Transfer_EdgePrior(int from,int to,int mode,flex_t baseCost)
{
    if (!transfer.edgeLoaded) return 0;
    const BotNode *a=&bot.nodes[from],*b=&bot.nodes[to];
    flex_t dz=b->pos.z-a->pos.z;
    flex_t x[10]={Bot_Distance(a->pos,b->pos),dz,fabsf(dz),(flex_t)mode,
        (a->sector && (a->sector->flags&SITH_SECTOR_UNDERWATER)) ? 1.0f : 0.0f,
        (b->sector && (b->sector->flags&SITH_SECTOR_UNDERWATER)) ? 1.0f : 0.0f,
        b->item>=0 ? 1.0f : 0.0f,baseCost,(flex_t)a->nEdges,(flex_t)b->nEdges};
    flex_t score=transfer.edgeBias;
    for (int i=0;i<10;++i) score+=transfer.edgeWeight[i]*(x[i]-transfer.edgeCenter[i])/transfer.edgeScale[i];
    if (score>30.0f) score=30.0f; else if (score<-30.0f) score=-30.0f;
    flex_t success=1.0f/(1.0f+expf(-score));
    return (1.0f-success)*4.0f;
}

static const char *Transfer_Mode(int ctf,int flags)
{
    if (flags&MULTIMODEFLAG_COOP) return "unsupported";
    if (ctf) return (flags&MULTIMODEFLAG_TEAMS) ? "ctf" : "unsupported";
    if (flags&MULTIMODEFLAG_TEAMS) return (flags&MULTIMODEFLAG_100) ? "tdm" : "unsupported";
    return "ffa";
}

/* Same engine resource layer and relative path used by sithWorld_Load.
 * Hash uncompressed, actually resolved JKL bytes, including custom episodes. */
static int Transfer_MapDigest(char out[65])
{
    if (!std_g_pHS || !bot.world || !bot.world->map_jkl_fname[0]) return 0;
    char path[72]; snprintf(path,sizeof(path),"jkl%c%s",LEC_PATH_SEPARATOR_CHR,bot.world->map_jkl_fname);
    stdFile_t file=std_g_pHS->fileOpen(path,"rb");
    if (!file) return 0;
    EVP_MD_CTX *ctx=EVP_MD_CTX_new(); unsigned char hash[32],chunk[8192]; unsigned size=0;
    int total=std_g_pHS->fileSize(file),left=total;
    int ok=total>0 && total<=128*1024*1024 && ctx && EVP_DigestInit_ex(ctx,EVP_sha256(),NULL);
    while (ok && left>0) {
        size_t n=(size_t)left>sizeof(chunk) ? sizeof(chunk) : (size_t)left;
        ok=std_g_pHS->fileRead(file,chunk,n)==n && EVP_DigestUpdate(ctx,chunk,n);
        left-=(int)n;
    }
    if (ok) ok=EVP_DigestFinal_ex(ctx,hash,&size) && size==32;
    if (ctx) EVP_MD_CTX_free(ctx);
    std_g_pHS->fileClose(file);
    if (ok) for (int i=0;i<32;++i) snprintf(out+2*i,3,"%02x",hash[i]);
    return ok;
}

/* A graph's insertion order depends on spawn. Key geometry and sector rather
 * than the process-local node ordinal, with 1/65536-unit precision. */
static uint64_t Transfer_Node(const BotNode *node)
{
    uint64_t key=14695981039346656037ULL;
    int32_t v[]={node->sector ? (int)node->sector->id : -1,(int32_t)llround(node->pos.x*65536.0),
                 (int32_t)llround(node->pos.y*65536.0),(int32_t)llround(node->pos.z*65536.0)};
    for (int i=0;i<4;++i) { key^=(uint32_t)v[i]; key*=1099511628211ULL; }
    return key ? key : 1;
}

static unsigned Transfer_Bucket(uint64_t a,uint64_t b,int m)
{ return (unsigned)((a^(a>>32)^b^(b>>32)^(uint64_t)m*131)&255); }

static void Transfer_Index(void)
{
    memset(transfer.bucket,0,sizeof(transfer.bucket));
    for (int i=0;i<transfer.recall.count;++i) {
        NavEdgeRecord r=transfer.recall.rows[i]; unsigned k=Transfer_Bucket(r.from,r.to,r.mode);
        transfer.next[i]=transfer.bucket[k]; transfer.bucket[k]=i+1;
    }
}

static int Transfer_Match(const char *scope,const char *map,const char *expectedScope,const char *expectedMap)
{
    return map[0] && expectedMap && expectedScope && !strcmp(map,expectedMap) && !strcmp(scope,expectedScope) &&
        (!strncmp(scope,"ffa/guns/",9) || !strncmp(scope,"tdm/guns/",9));
}

static void Transfer_Context(SithThing *self,int newWorld)
{
    int flags=sithNet_MultiModeFlags;
    int rank=(int)sithInventory_GetInventory(self,SITHBIN_JEDI_RANK);
    const char *mode=Transfer_Mode(nav.ctf,flags);
    char scope[48]; snprintf(scope,sizeof(scope),"%s/%s/%s",mode,bot.sabersOnly ? "sabers" : "guns",
                             bot.forceEnabled && rank>0 ? "force" : "noforce");
    transfer.wall=time(NULL);
    if (newWorld || transfer.world!=bot.world) {
        transfer.world=bot.world; transfer.map[0]=0;
        (void)Transfer_MapDigest(transfer.map);
        for(int i=0;i<bot.nNodes;++i) transfer.keys[i]=Transfer_Node(&bot.nodes[i]);
        transfer.navCount=bot.nNodes; transfer.routeStart=-1;
    } else if (transfer.initialized && !strcmp(scope,transfer.scope) &&
               flags==transfer.flags && rank==transfer.rank) return;
    if (transfer.initialized && transfer.recall.lock>=0) close(transfer.recall.lock);
    transfer.initialized=1; transfer.flags=flags; transfer.rank=rank;
    strcpy(transfer.scope,scope); transfer.nextState=0;
    transfer.trace=getenv("ADJOIN_RED_TRACE") && !strcmp(getenv("ADJOIN_RED_TRACE"),"1");
    (void)Transfer_LoadEdgeModel();
    transfer.applies=Transfer_Match(scope,transfer.map,getenv("ADJOIN_RED_MODEL_SCOPE"),getenv("ADJOIN_RED_MODEL_MAP_SHA256"));
    char file[1024]={0}; const char *dir=getenv("ADJOIN_NAV_CACHE");
    if (dir && *dir=='/' && transfer.map[0] && strcmp(mode,"unsupported")) {
        int written=snprintf(file,sizeof(file),"%s/%s-%s-%s-%s-%x-r%d.nav",dir,transfer.map,mode,
            bot.sabersOnly ? "s" : "g",bot.forceEnabled ? "f" : "n",flags,rank);
        if (written<0 || (size_t)written>=sizeof(file)) file[0]=0;
    }
    NR_Open(&transfer.recall,file,transfer.wall); Transfer_Index();
    transfer.failures=transfer.arrivals=0;
    if (transfer.trace) fprintf(stderr,"BOT_RED_CONTEXT name=%s map=%s map_sha=%s scope=%s flags=%x rank=%d sabers=%d force=%d team=%u bindings=%d nodes=%d sectors=%u scope_match=%d cache=%s loaded_edges=%d\n",
        bot.name,bot.world->map_jkl_fname,transfer.map[0]?transfer.map:"unknown",scope,flags,rank,bot.sabersOnly,
        bot.forceEnabled,self->actorParams.pPlayer->teamNum,nav.ctf,bot.nNodes,(unsigned)bot.world->numSectors,
        transfer.applies,transfer.recall.lock>=0 ? "persistent" : "session",transfer.recall.loaded);
}

/* Only existing legal directed edges reach this function. The returned
 * nonnegative surcharge does not create a traversal or relax a constraint. */
static flex_t Transfer_Cost(int from,int to,int mode,flex_t baseCost)
{
    if (!transfer.initialized || from<0 || to<0 ||
        from>=transfer.navCount || to>=transfer.navCount) return 0;
    /* Regenerated tactics trees add the Brain prior inside Bot_SearchPaths
     * (JK_BOT_BRAIN_PLANNER_PRIOR); frozen trees keep it here instead -
     * never both, or the same prior would be charged twice. */
#ifdef JK_BOT_BRAIN_PLANNER_PRIOR
    flex_t extra=0;
#else
    flex_t extra=Transfer_EdgePrior(from,to,mode,baseCost);
#endif
    if (!transfer.recall.count) return extra;
    uint64_t a=transfer.keys[from],b=transfer.keys[to];
    unsigned k=Transfer_Bucket(a,b,mode);
    for (int it=transfer.bucket[k];it;it=transfer.next[it-1]) {
        NavEdgeRecord r=transfer.recall.rows[it-1];
        if (r.from==a && r.to==b && r.mode==mode) {
            int level=NR_Level(r,transfer.wall);
            if (transfer.trace && level && !transfer.searchLogged) {
                transfer.searchLogged=1;
                fprintf(stderr,"BOT_NAV_COST name=%s t=%.3f from=%d to=%d edge=%d base=graph extra=%d\n",
                    bot.name,(double)bot.now,from,to,mode,level*2);
            }
            return extra+(flex_t)(level*2);
        }
    }
    return extra;
}

static void Transfer_Observe(int node,int failed)
{
    if (!transfer.initialized || !transfer.map[0] || !strcmp(Transfer_Mode(nav.ctf,transfer.flags),"unsupported") ||
        !bot.followingRoute || bot.routePos<0 || bot.routePos>=bot.routeCount || bot.route[bot.routePos]!=node) return;
    int from=bot.routePos>0 ? bot.route[bot.routePos-1] : transfer.routeStart;
    if (from<0 || node<0 || from==node || from>=transfer.navCount || node>=transfer.navCount) return;
    const BotNode *n=&bot.nodes[from];
    int mode=-1; flex_t baseCost=0;
    for (int i=0;i<n->nEdges;++i) if (n->edges[i].to==node) { mode=n->edges[i].drop; baseCost=n->edges[i].cost; break; }
    if (mode<0) return;
    uint64_t a=transfer.keys[from],b=transfer.keys[node];
    /* BrainStore training telemetry: geometry features for the global edge
     * model, emitted for arrivals as well as stalls. Log-only; planning and
     * recall behavior are unchanged. */
    if (transfer.trace) {
        const BotNode *to=&bot.nodes[node];
        fprintf(stderr,"BOT_EDGE_ATTEMPT name=%s t=%.3f event=%s from_key=%" PRIx64 " to_key=%" PRIx64 " edge=%d dist_mm=%lld dz_mm=%lld from_water=%d to_water=%d dest_item=%d base_cost_milli=%lld degree_from=%d degree_to=%d\n",
            bot.name,(double)bot.now,failed ? "stall" : "arrive",a,b,mode,
            (long long)llround(Bot_Distance(n->pos,to->pos)*1000.0),
            (long long)llround(((double)to->pos.z-(double)n->pos.z)*1000.0),
            !!(n->sector && (n->sector->flags&SITH_SECTOR_UNDERWATER)),
            !!(to->sector && (to->sector->flags&SITH_SECTOR_UNDERWATER)),
            to->item>=0,(long long)llround((double)baseCost*1000.0),n->nEdges,to->nEdges);
        fflush(stderr);
    }
    if (!failed) ++transfer.arrivals; else ++transfer.failures;
    int before;
    int now=NR_Observe(&transfer.recall,a,b,mode,failed,transfer.wall,&before);
    if (failed || before) {
        Transfer_Index(); transfer.searchLogged=0;
        int saved=NR_Save(&transfer.recall);
        if (transfer.trace) fprintf(stderr,"BOT_NAV_LEARN name=%s t=%.3f event=%s from=%d to=%d from_key=%" PRIx64 " to_key=%" PRIx64 " edge=%d before=%d after=%d saved=%d\n",
            bot.name,(double)bot.now,failed ? "stall" : "arrive",from,node,a,b,mode,before*2,now*2,saved);
    }
}

static void Transfer_State(SithThing *self)
{
    if (!transfer.trace || bot.now<transfer.nextState) return;
    transfer.nextState=bot.now+0.20f;
    int team=self->actorParams.pPlayer->teamNum;
    int foe=bot.targetSlot>=0 && bot.targetSlot<JKPLAYER_NUM_INFOS ? (int)jkPlayer_playerInfos[bot.targetSlot].teamNum : -1;
    const char *objectives[]={"none","join","capture","return","recover","escort","defend","intercept","air"};
    int carrier[2]={-1,-1},atBase[2]={-1,-1},flagId[2]={-1,-1};
    if (nav.ctf) for (int i=0;i<2;++i) {
        SithThing *flag=Bot_NavThing(nav.flag[i]),*base=Bot_NavThing(nav.base[i]),*who=Bot_FlagCarrier(i+1);
        carrier[i]=who ? (int)who->idx : -1; flagId[i]=nav.flag[i];
        if (flag && base) atBase[i]=!who && Bot_Distance(flag->position,base->position)<0.16f;
    }
    fprintf(stderr,"BOT_RED_NAV name=%s t=%.3f scope=%s team=%d target_team=%d objective=%s objective_valid=%d own_score=%d red_score=%d gold_score=%d flags=%d,%d carriers=%d,%d home=%d,%d nodes=%d edges=%d ready=%d sector=%u goal=%d path=%d/%d fwd=%.5f slide=%.5f fire=%d,%d weapon=%d arrivals=%u stalls=%u\n",
        bot.name,(double)bot.now,transfer.scope,team,foe,(unsigned)nav.objective<9?objectives[nav.objective]:"unknown",
        nav.objectiveValid,(int)self->actorParams.pPlayer->score,sithNet_teamScore[1],sithNet_teamScore[2],
        flagId[0],flagId[1],carrier[0],carrier[1],atBase[0],atBase[1],bot.nNodes,bot.graphEdges,bot.graphDone,
        (unsigned)self->sector->id,bot.goal,bot.routePos,bot.routeCount,(double)bot.axes[INPUT_FUNC_FORWARD],
        (double)bot.axes[INPUT_FUNC_SLIDE],bot.keys[INPUT_FUNC_FIRE1],bot.keys[INPUT_FUNC_FIRE2],
        sithInventory_GetCurrentWeapon(self),transfer.arrivals,transfer.failures);
}
