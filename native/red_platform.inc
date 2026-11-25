/* Local recovery from verified static footing in fall-death sectors. */
static int Platform_Step(SithThing *self, rdVector3 dir, rdVector3 *ahead,
                         int *nextFixture, int *probes, int *unsupported)
{
    const flex_t step=0.04f;
    flex_t distance=0.22f+Bot_Min(0.24f,0.16f*Bot_Horizontal(self->physicsParams.vel));
    int count=(int)ceilf(distance/step);
    SithSector *hint=self->sector;
    rdVector3 previous=self->position;
    for (int n=1;n<=count;n++) {
        rdVector3 pos={self->position.x+dir.x*step*n,self->position.y+dir.y*step*n,previous.z+0.055f};
        rdVector3 floor; SithSector *sector; int fixture=-1;
        for (int lane=-1;lane<=1;lane++) {
            rdVector3 probe=pos,foot; SithSector *on=NULL;int id=-1;
            probe.x-=lane*dir.y*self->moveSize*0.65f;
            probe.y+=lane*dir.x*self->moveSize*0.65f;
            ++*probes;
            if (!Bot_StandingFloor(probe,hint,BOT_FOOT_HEIGHT+0.14f,&foot,&on,1,&id) ||
                fabsf(foot.z-previous.z)>0.065f) { ++*unsupported;return 0; }
            if (!lane) { floor=foot;sector=on;fixture=id; }
        }
        if (!Bot_Clear(self,hint,previous,floor,self->collideSize*0.85f,0)) return 0;
        hint=sector; previous=floor; *nextFixture=fixture;
    }
    *ahead=previous; return 1;
}

/* Use the nearest ordinary passable doorway and, where present, the next
 * stationary fixture leading toward it. Geometry still qualifies every step. */
static int Platform_Heading(SithThing *self,rdVector3 *dir)
{
    flex_t best=1e20f; int sector=-1; rdVector3 goal={0};
    for (SithSurfaceAdjoin *a=self->sector->adjoins;a;a=a->next) {
        rdVector3 p;
        if (!(a->flags&SITHSURF_ADJOIN_ALLOW_MOVEMENT) || (a->flags&SITHSURF_ADJOIN_ALLOW_AI_ONLY) ||
            !Bot_SectorSafe(a->sector) || !a->surface || !Bot_FaceCenter(a->surface,&p)) continue;
        flex_t d=Bot_Distance(p,self->position);
        if (d<best) {best=d;goal=p;sector=(int)a->sector->id;}
    }
    if (sector<0) return -1;
    if (nav.ctf && nav.objectiveValid) goal=nav.objectivePos;
    rdVector3 toward=Bot_Sub(goal,self->position);
    flex_t length=Bot_Horizontal(toward);
    if (length<0.01f) return -1;
    *dir=(rdVector3){toward.x/length,toward.y/length,0};
    /* Aim for the centre of the next bridge panel, not a diagonal line
       toward a wide portal that can run along the outside of the deck. */
    best=1e20f;
    rdVector3 exitDirection=*dir;
    for (SithThing *t=self->sector->pFirstThingInSector;t;t=t->pNextThingInSector) {
        if (t==self->attachedThing || !Bot_StaticFixture(t) || !(t->flags&SITH_TF_STANDABLE)) continue;
        rdVector3 v=Bot_Sub(t->position,self->position); flex_t d=Bot_Horizontal(v);
        if (d<0.08f || d>1.8f || d>=length || fabsf(v.z)>0.45f ||
            v.x*exitDirection.x+v.y*exitDirection.y<0.72f*d || d>=best) continue;
        best=d; *dir=(rdVector3){v.x/d,v.y/d,0};
    }
    return sector;
}

static void Platform_Recover(SithThing *self)
{
    static flex_t nextLog; static SithWorld *world;
    if (!self->sector || !(self->sector->flags&SITH_SECTOR_FALLDEATH) ||
        self->sector->flags&(SITH_SECTOR_NOACTORENTER|SITH_SECTOR_UNDERWATER) ||
        !(self->attach_flags&SITH_ATTACH_THINGFACE) || !Bot_StaticFixture(self->attachedThing) ||
        !(self->attachedThing->flags&SITH_TF_STANDABLE) || bot.goal>=0 ||
        bot.axes[INPUT_FUNC_FORWARD] || bot.axes[INPUT_FUNC_SLIDE] || Bot_NavigationWaiting(self) ||
        nav.waterExitUntil>0 || nav.combatJumpUntil>bot.now) return;
    rdVector3 heading;
    int exit=Platform_Heading(self,&heading);
    if (exit<0) return;
    static const int angles[]={0,1,-1,2,-2,3,-3,4,-4,5,-5,6,-6};
    int probes=0,unsupported=0,next=-1;rdVector3 ahead={0};
    for (unsigned i=0;i<sizeof(angles)/sizeof(*angles);i++) {
        flex_t angle=angles[i]*(flex_t)(M_PI/12);
        rdVector3 dir={heading.x*cosf(angle)-heading.y*sinf(angle),
                       heading.x*sinf(angle)+heading.y*cosf(angle),0};
        if (!Platform_Step(self,dir,&ahead,&next,&probes,&unsupported)) continue;
        bot.keys[INPUT_FUNC_JUMP]=bot.keys[INPUT_FUNC_FAST]=0;
        if (bot.targetSlot<0) Bot_Aim(self,ahead,0);
        Bot_ThrustAxes(self,dir,0);
        bot.axes[INPUT_FUNC_FORWARD]*=0.65f;bot.axes[INPUT_FUNC_SLIDE]*=0.65f;
        bot.tele.moved=1;
        if (world!=bot.world) {world=bot.world;nextLog=0;}
        if (transfer.trace && bot.now>=nextLog) {
            nextLog=bot.now+0.25f;
            fprintf(stderr,"BOT_PLATFORM_SUPPORT name=%s t=%.3f sector=%u fixture=%d next_fixture=%d pos=%.5f,%.5f,%.5f ahead=%.5f,%.5f,%.5f probes=%d void_rejects=%d exit_sector=%d fwd=%.5f slide=%.5f\n",
                    bot.name,(double)bot.now,(unsigned)self->sector->id,(int)(self->attachedThing-bot.world->aThings),next,
                    (double)self->position.x,(double)self->position.y,(double)self->position.z,
                    (double)ahead.x,(double)ahead.y,(double)ahead.z,probes,unsupported,exit,
                    (double)bot.axes[INPUT_FUNC_FORWARD],(double)bot.axes[INPUT_FUNC_SLIDE]);
        }
        return;
    }
}
