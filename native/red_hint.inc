/* Authored, map-scoped walking hints. Every step still requires live support. */
#define HINT_MAX 32
typedef struct { int sector,fixture; rdVector3 pos; } HintPoint;
static struct {
    SithWorld *world; char map[65],digest[65];
    HintPoint points[HINT_MAX]; int count,life,active,seq,done;
    flex_t nextLog; rdVector3 last;
} hint;

static int Hint_Parse(char *s,const char *map,HintPoint *points,int *count)
{
    const char prefix[]="RED_ROUTE_HINT_V1 ";
    if (strncmp(s,prefix,sizeof(prefix)-1)) return 0;
    s+=sizeof(prefix)-1;
    if (strlen(map)!=64 || strncmp(s,map,64) || !isspace((unsigned char)s[64])) return 0;
    s+=64;
    if (!Red_Int(&s,2,HINT_MAX,count)) return 0;
    for (int i=0;i<*count;i++) {
        int v[3];
        if (!Red_Int(&s,0,65535,&points[i].sector) || !Red_Int(&s,-1,65535,&points[i].fixture)) return 0;
        for (int j=0;j<3;j++) if (!Red_Int(&s,-10000000,10000000,&v[j])) return 0;
        points[i].pos=(rdVector3){v[0]*0.001f,v[1]*0.001f,v[2]*0.001f};
        if (i && Bot_Distance(points[i].pos,points[i-1].pos)>1.5f) return 0;
    }
    while (isspace((unsigned char)*s)) ++s;
    return !*s && points[0].fixture>=0 && points[*count-1].fixture==-1 &&
        points[0].sector!=points[*count-1].sector;
}

static int Hint_Read(const char *path,const char *expected)
{
    if (!path || path[0]!='/' || !expected || !Custom_Hex(expected)) return 0;
    FILE *file=fopen(path,"rb"); if (!file) return 0;
    char bytes[8193];size_t n=fread(bytes,1,sizeof(bytes),file);
    int valid=n && n<sizeof(bytes) && !ferror(file) && !memchr(bytes,0,n);
    fclose(file);
    if (!valid) return 0;
    unsigned char hash[SHA256_DIGEST_LENGTH];
    if (!SHA256((unsigned char*)bytes,n,hash)) return 0;
    for (unsigned i=0;i<sizeof(hash);i++) snprintf(hint.digest+2*i,3,"%02x",hash[i]);
    bytes[n]=0;
    int count=0;
    if (strcmp(hint.digest,expected) || !Hint_Parse(bytes,transfer.map,hint.points,&count)) return 0;
    for (int i=0;i<count;i++) {
        const HintPoint *p=&hint.points[i];
        if (p->sector>=bot.world->numSectors || p->fixture>=bot.world->numThings) return 0;
        if (p->fixture>=0) {
            const SithThing *t=&bot.world->aThings[p->fixture];
            if (!Bot_StaticFixture(t) || !(t->flags&SITH_TF_STANDABLE) || !t->sector ||
                (int)t->sector->id!=p->sector) return 0;
        }
    }
    hint.count=count;return 1;
}

static void Hint_Log(SithThing *self,const char *phase,const char *status,int fixture)
{
    if (!transfer.trace) return;
    rdVector3 goal={0};
    if (hint.seq>=0 && hint.seq<hint.count) goal=hint.points[hint.seq].pos;
    fprintf(stderr,"BOT_ROUTE_HINT phase=%s status=%s name=%s pid=%ld t=%.3f life=%d map_sha=%s hint_sha=%s seq=%d sector=%u fixture=%d pos=%.5f,%.5f,%.5f goal=%.5f,%.5f,%.5f fwd=%.5f slide=%.5f\n",
        phase,status,bot.name,(long)getpid(),(double)bot.now,red.life,transfer.map,hint.digest[0]?hint.digest:"none",
        hint.seq,(unsigned)self->sector->id,fixture,(double)self->position.x,(double)self->position.y,
        (double)self->position.z,(double)goal.x,(double)goal.y,(double)goal.z,
        (double)bot.axes[INPUT_FUNC_FORWARD],(double)bot.axes[INPUT_FUNC_SLIDE]);
}

static int Hint_Walk(SithThing *self)
{
    int fixture=(self->attach_flags&SITH_ATTACH_THINGFACE) && self->attachedThing ?
        (int)(self->attachedThing-bot.world->aThings) : -1;
    if (hint.world!=bot.world || strcmp(hint.map,transfer.map)) {
        memset(&hint,0,sizeof(hint));hint.world=bot.world;
        snprintf(hint.map,sizeof(hint.map),"%s",transfer.map);
        const char *path=getenv("ADJOIN_ROUTE_HINT"),*sha=getenv("ADJOIN_ROUTE_HINT_SHA256");
        if (path || sha) {int ok=Hint_Read(path,sha);Hint_Log(self,"load",ok?"ready":"rejected",fixture);}
    }
    if (!hint.count || nav.ctf || nav.seekingSurface || nav.waterExitUntil>0 ||
        self->sector->flags&(SITH_SECTOR_NOACTORENTER|SITH_SECTOR_UNDERWATER)) return 0;
    if (hint.life!=red.life) {
        hint.life=red.life;hint.active=hint.done=hint.seq=0;hint.nextLog=0;
    }
    if (hint.done) return 0;
    HintPoint *p=&hint.points[hint.seq];
    if (!hint.active) {
        if ((int)self->sector->id!=p->sector || fixture!=p->fixture || Bot_Distance(p->pos,self->position)>0.70f) return 0;
        hint.active=1;hint.last=self->position;Hint_Log(self,"start","ready",fixture);
    }
    if (Bot_Distance(hint.last,self->position)>0.55f) {hint.active=0;hint.done=1;Hint_Log(self,"blocked","discontinuity",fixture);return 0;}
    hint.last=self->position;
    int sector=(int)self->sector->id;
    if (hint.seq==hint.count-1 && sector==p->sector && Bot_SectorSafe(self->sector) &&
        Bot_Distance(self->position,p->pos)<0.42f) {
        Hint_Log(self,"exit","reached",fixture);hint.active=0;hint.done=1;
        bot.goal=-1;bot.routeCount=0;bot.nextPlan=0;return 0;
    }
    if (hint.seq<hint.count-1 && sector==p->sector && fixture==p->fixture &&
        Bot_Horizontal(Bot_Sub(p->pos,self->position))<0.09f && fabsf(self->position.z-p->pos.z)<0.15f) {
        Hint_Log(self,"arrive","reached",fixture);p=&hint.points[++hint.seq];
    }
    if (fixture<0 || !Bot_StaticFixture(self->attachedThing) || !(self->attachedThing->flags&SITH_TF_STANDABLE)) return 0;
    rdVector3 dir=Bot_Sub(p->pos,self->position);flex_t length=Bot_Horizontal(dir);
    if (length<0.001f || length>1.6f || fabsf(dir.z)>0.20f) return 0;
    dir.x/=length;dir.y/=length;dir.z=0;
    int probes=0,rejects=0,next=-1;rdVector3 ahead={0};
    if (!Platform_Step(self,dir,&ahead,&next,&probes,&rejects)) {
        if (bot.now>=hint.nextLog) {Hint_Log(self,"blocked","footing",fixture);hint.nextLog=bot.now+0.5f;}
        return 0;
    }
    bot.keys[INPUT_FUNC_JUMP]=bot.keys[INPUT_FUNC_FAST]=0;
    if (bot.targetSlot<0) Bot_Aim(self,ahead,0);
    Bot_ThrustAxes(self,dir,0);
    bot.axes[INPUT_FUNC_FORWARD]*=0.65f;bot.axes[INPUT_FUNC_SLIDE]*=0.65f;bot.tele.moved=1;
    /* This local segment owns the legs, so it cannot be attributed as
       feedback to an unrelated ordinary graph goal selected this tick. */
    bot.progressPos=self->position;bot.stuckAt=bot.now;bot.routeStallTime=0;
    if (bot.now>=hint.nextLog) {Hint_Log(self,"step","applied",fixture);hint.nextLog=bot.now+0.25f;}
    return 1;
}
