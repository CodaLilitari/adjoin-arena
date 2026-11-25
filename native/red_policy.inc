/* Per-process Red decision model. Signed integer arithmetic matches the trainer. */
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <ctype.h>
#include <string.h>
#include <openssl/sha.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    int center[9], scale[9], b1[8], w1[8][9], b2, w2[8];
} RedNet;

static int Red_Int(char **cursor, int low, int high, int *out)
{
    char *s=*cursor, *end;
    while (isspace((unsigned char)*s)) ++s;
    errno=0;
    long v=strtol(s,&end,10);
    if (end==s || (*end && !isspace((unsigned char)*end)) || errno || v<low || v>high) return 0;
    *out=(int)v; *cursor=end; return 1;
}

static int Red_Parse(char *s, RedNet *net)
{
    const char *header="RED_NEURAL_V1";
    size_t n=strlen(header);
    if (strncmp(s,header,n) || !isspace((unsigned char)s[n])) return 0;
    s+=n;
    int a,b;
    if (!Red_Int(&s,9,9,&a) || !Red_Int(&s,8,8,&b)) return 0;
    for (int j=0;j<9;++j) if (!Red_Int(&s,-1073741824,1073741824,&net->center[j])) return 0;
    for (int j=0;j<9;++j) if (!Red_Int(&s,1,1073741824,&net->scale[j])) return 0;
    for (int k=0;k<8;++k) {
        if (!Red_Int(&s,-33554432,33554432,&net->b1[k])) return 0;
        for (int j=0;j<9;++j) if (!Red_Int(&s,-16384,16384,&net->w1[k][j])) return 0;
    }
    if (!Red_Int(&s,-33554432,33554432,&net->b2)) return 0;
    for (int k=0;k<8;++k) if (!Red_Int(&s,-16384,16384,&net->w2[k])) return 0;
    while (isspace((unsigned char)*s)) ++s;
    return *s==0;
}

static int64_t Red_Score(const RedNet *net,const int x[9])
{
    int z[9];
    for (int j=0;j<9;++j) {
        int64_t v=((int64_t)x[j]-net->center[j])*1024/net->scale[j];
        z[j]=v < -2048 ? -2048 : v > 2048 ? 2048 : (int)v;
    }
    int64_t score=net->b2;
    for (int k=0;k<8;++k) {
        int64_t v=net->b1[k];
        for (int j=0;j<9;++j) v+=(int64_t)net->w1[k][j]*z[j];
        v/=1024;
        score+=(int64_t)net->w2[k]*(v<0 ? 0 : v>32768 ? 32768 : v);
    }
    return score;
}

/* Hash the same bounded bytes that were parsed. A renamed/replaced weights
 * file after startup cannot change a running match. */
static int Red_Load(const char *path,const char *expected,RedNet *net,char digest[65])
{
    if (!path || !expected || strlen(expected)!=64) return 0;
    FILE *file=fopen(path,"rb");
    if (!file) return 0;
    char bytes[8193];
    size_t n=fread(bytes,1,sizeof(bytes),file);
    int ok=n && n<sizeof(bytes) && !ferror(file) && !memchr(bytes,0,n);
    fclose(file);
    if (!ok) return 0;
    unsigned char hash[SHA256_DIGEST_LENGTH];
    if (!SHA256((unsigned char *)bytes,n,hash)) return 0;
    for (size_t i=0;i<sizeof(hash);++i) snprintf(digest+i*2,3,"%02x",hash[i]);
    bytes[n]=0;
    return !strcmp(digest,expected) && Red_Parse(bytes,net);
}

#ifndef RED_POLICY_TEST
static struct {
    RedNet net;
    int trace, learned, rejected, seq, life, live, acted, frame, readMask;
    char digest[65];
    struct {
        int pending, x[9], target, item, teacher, selected;
        const char *owner;
        flex_t fwd,slide;
    } decision;
} red;

static const char *Red_Model(void) { return red.learned ? red.digest : "teacher"; }

static uint64_t Red_Monotonic(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC,&ts)) abort();
    return (uint64_t)ts.tv_sec*1000000000u+(uint64_t)ts.tv_nsec;
}

static void Red_Configure(void)
{
    const char *path=getenv("ADJOIN_RED_MODEL"), *expected=getenv("ADJOIN_RED_MODEL_SHA256");
    const char *trace=getenv("ADJOIN_RED_TRACE");
    memset(&red,0,sizeof(red));
    red.trace=trace && !strcmp(trace,"1");
    if (path || expected) {
        red.learned=Red_Load(path,expected,&red.net,red.digest);
        red.rejected=!red.learned;
    }
    if (red.trace || path || expected)
        fprintf(stderr,"BOT_RED_MODEL name=%s pid=%ld mode=%s model=%s status=%s\n",bot.name,(long)getpid(),
            red.learned ? "learned" : red.rejected ? "fallback" : "teacher",Red_Model(),red.rejected ? "rejected" : "ready");
}

static void Red_Marker(const char *event)
{
    if (red.trace) fprintf(stderr,"%s name=%s pid=%ld mono_ns=%" PRIu64 " slot=%d net=%u life=%d frame=%d t=%.4f game_ms=%u fwd=%.6f slide=%.6f model=%s\n",
        event,bot.name,(long)getpid(),Red_Monotonic(),playerThingIdx,
        sithPlayer_g_pLocalPlayer ? (unsigned)sithPlayer_g_pLocalPlayer->playerNetId : 0,
        red.life,red.frame,(double)bot.now,(unsigned)sithTime_g_msecGameTime,(double)bot.axes[INPUT_FUNC_FORWARD],
        (double)bot.axes[INPUT_FUNC_SLIDE],Red_Model());
}

static int Red_RouteItem(void)
{
    if (bot.armItem) return bot.armItem-1;
    if (bot.goal>=0 && bot.goal<bot.nNodes && bot.routePos<bot.routeCount) return bot.nodes[bot.goal].item;
    return -1;
}

static int Red_Amount(flex_t v)
{
    if (!isfinite(v) || v<=0) return 0;
    return v>1000000 ? 1000000 : (int)(v+0.5f);
}

static int Red_Ammo(SithThing *self,int gun)
{
    int bin;
    switch (gun) {
    case SITHBIN_BRYARPISTOL: case SITHBIN_STORMTROOPER_RIFLE: bin=SITHBIN_ENERGY; break;
    case SITHBIN_TUSKEN_PROD: case SITHBIN_REPEATER: case SITHBIN_CONCUSSION_RIFLE: bin=SITHBIN_POWER; break;
    case SITHBIN_RAIL_DETONATOR: bin=SITHBIN_RAILCHARGES; break;
    case SITHBIN_THERMAL_DETONATOR: case SITHBIN_SEQUENCER_CHARGE: bin=gun; break;
    default: return 0;
    }
    return Red_Amount(sithInventory_GetInventory(self,bin));
}

/* Enter only with current LOS and a pre-existing valid equipment objective.
 * Merely seeing another player never creates an equipment objective. */
static int Red_Choose(SithThing *self,SithThing *target,flex_t distance,int teacher)
{
    if ((!red.trace && !red.learned) || !Bot_EquipmentMode() || Bot_SupplyOrder() ||
        (!self->attach_flags && !(self->sector->flags&SITH_SECTOR_UNDERWATER))) return teacher;
    int idx=Red_RouteItem();
    SithThing *item=Bot_NavThing(idx);
    /* Reading the original utility can refresh a cached unavailability bit.
     * Let Red discover that return itself; querying an already clear bit
     * cannot change its information about equipment or influence its plan. */
    if (idx>=0 && idx<BOT_NODES && nav.unavailable[idx]) return teacher;
    if (!item || Bot_GearValue(self,idx)<=0 || Bot_AtEquipment(self,item)) return teacher;
    if (bot.armItem && (item->guid!=bot.armGuid || item->signature!=bot.armSignature ||
        Bot_Distance(item->position,bot.armPosition)>0.035f ||
        (!bot.armDirect && (bot.armNode<1 || bot.goal!=bot.armNode-1 || bot.routePos>=bot.routeCount)) ||
        (Bot_DeferSupplyApproaches(self) && Bot_OnDeferredCrossing() && Bot_OptionalSupply(self,item)))) return teacher;
    int *x=red.decision.x;
    x[0]=Red_Amount(self->actorParams.health); x[1]=Red_Amount(sithInventory_GetInventory(self,SITHBIN_SHIELDS));
    x[2]=Red_Amount(distance*1000); x[3]=Red_Amount(Bot_Distance(self->position,item->position)*1000);
    x[4]=sithInventory_GetCurrentWeapon(self); x[5]=Red_Ammo(self,x[4]);
    x[6]=!!Bot_LivePack(item); x[7]=!!(self->sector->flags&SITH_SECTOR_UNDERWATER);
    x[8]=bot.routeCount>bot.routePos ? bot.routeCount-bot.routePos : 0;
    red.decision.pending=1; red.decision.target=target->idx; red.decision.item=idx;
    red.decision.teacher=teacher;
    red.decision.selected=red.learned ? Red_Score(&red.net,x)>=0 : teacher;
    red.decision.owner="engage";
    return red.decision.selected;
}

static void Red_FinishDecision(void)
{
    if (!red.decision.pending || !red.trace) return;
    const char *owner=red.decision.owner;
    flex_t a=bot.axes[INPUT_FUNC_FORWARD], b=bot.axes[INPUT_FUNC_SLIDE];
    if (a!=red.decision.fwd || b!=red.decision.slide) owner="late-override";
    else if (!a && !b) owner="stationary";
    int *x=red.decision.x;
    fprintf(stderr,"BOT_DUEL name=%s t=%.4f seq=%d life=%d target=%d item=%d f=%d,%d,%d,%d,%d,%d,%d,%d,%d teacher=%d selected=%d applied=%d owner=%s model=%s forward=%.6f slide=%.6f fire1=%d fire2=%d pid=%ld mono_ns=%" PRIu64 " game_ms=%u\n",
        bot.name,(double)bot.now,++red.seq,red.life,red.decision.target,red.decision.item,
        x[0],x[1],x[2],x[3],x[4],x[5],x[6],x[7],x[8],red.decision.teacher,red.decision.selected,
        !strcmp(owner,"supply"),owner,Red_Model(),(double)a,(double)b,bot.keys[INPUT_FUNC_FIRE1],
        bot.keys[INPUT_FUNC_FIRE2],(long)getpid(),Red_Monotonic(),(unsigned)sithTime_g_msecGameTime);
}

static void Red_State(SithThing *self,int dead)
{
    if (!red.trace) return;
    static int previous[13];
    static flex_t heartbeat;
    int state[13];
    unsigned mask=0;
    for (int bin=SITHBIN_FISTS;bin<=SITHBIN_LIGHTSABER;++bin)
        if (sithInventory_IsInventoryAvailable(self,bin) && sithInventory_GetInventory(self,bin)>0) mask|=1u<<bin;
    state[0]=Red_Amount(self->actorParams.health);
    state[1]=Red_Amount(sithInventory_GetInventory(self,SITHBIN_SHIELDS));
    state[2]=mask; state[3]=sithInventory_GetCurrentWeapon(self);
    const int bins[]={SITHBIN_ENERGY,SITHBIN_POWER,SITHBIN_RAILCHARGES,SITHBIN_THERMAL_DETONATOR,SITHBIN_SEQUENCER_CHARGE};
    for (int j=0;j<5;++j) state[4+j]=Red_Amount(sithInventory_GetInventory(self,bins[j]));
    state[9]=sithPlayer_g_pLocalPlayer->numKills; state[10]=sithPlayer_g_pLocalPlayer->numKilled;
    state[11]=bot.targetSlot; state[12]=dead;
    if (bot.now<heartbeat && !memcmp(previous,state,sizeof(state))) return;
    heartbeat=bot.now+0.2f; memcpy(previous,state,sizeof(state));
    fprintf(stderr,"BOT_RED_STATE name=%s t=%.4f life=%d game_ms=%u mono_ns=%" PRIu64 " hp=%d shields=%d weapons=0x%x weapon=%d energy=%d power=%d rails=%d thermal=%d seqcharges=%d kills=%d deaths=%d target=%d dead=%d\n",
        bot.name,(double)bot.now,red.life,(unsigned)sithTime_g_msecGameTime,Red_Monotonic(),state[0],state[1],mask,
        state[3],state[4],state[5],state[6],state[7],state[8],state[9],state[10],state[11],state[12]);
}

static void Red_AxisRead(int functionId,flex_t value)
{
    if (!red.trace || !red.live || (functionId!=INPUT_FUNC_FORWARD && functionId!=INPUT_FUNC_SLIDE)) return;
    if (value && !red.acted) {
        red.acted=1;
        Red_Marker("BOT_RED_APPLY");
    }
    int bit=functionId==INPUT_FUNC_FORWARD ? 1 : 2;
    if (red.decision.pending && !(red.readMask&bit)) {
        red.readMask|=bit;
        fprintf(stderr,"BOT_RED_READ name=%s t=%.4f life=%d seq=%d axis=%s value=%.6f game_ms=%u mono_ns=%" PRIu64 "\n",
            bot.name,(double)bot.now,red.life,red.seq,bit==1 ? "forward" : "slide",(double)value,
            (unsigned)sithTime_g_msecGameTime,Red_Monotonic());
    }
}
#endif
