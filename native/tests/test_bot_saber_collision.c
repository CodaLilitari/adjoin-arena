/* A standing target has a single narrow mesh entirely below or above its
   origin. Use the same world/mesh raycast used by the stock JK blade. */
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
#include "AI/jkBot.c"
#include "World/sithActor.h"

int Main_bMotsCompat; /* These fixtures use Dark Forces II face collision. */
void stdPlatform_Memcpy32(void *dst,const void *src,uint32_t n) { memcpy(dst,src,n); }
int jk_printf(const char *format,...)
{
    va_list args; va_start(args,format);
    int result=vfprintf(stderr,format,args); va_end(args); return result;
}
int rdModel3_GetMeshMatrix(rdThing *thing,rdMatrix34 *orient,uint32_t node,rdMatrix34 *out)
{ (void)thing; (void)orient; (void)node; (void)out; abort(); /* MotS tree only */ }

static int player_contact(SithThing *a,SithThing *b,SithCollision *hit,int flags)
{ (void)a; (void)b; (void)hit; (void)flags; abort(); /* Tracing never moves things. */ }

static void engine_assert(const char *condition,const char *file,int line)
{ fprintf(stderr,"%s:%d: %s\n",file,line,condition); abort(); }

int main(void)
{
    SithWorld world={0}; SithSector sector={0}; SithThing self={0},enemy={0},blocker={0};
    HostServices services={.assert=engine_assert}; pSithHS=&services;
    sithWorld_g_pCurrentWorld=&world;
    sithCollision_AddCollisionHandler(SITH_THING_PLAYER,SITH_THING_PLAYER,player_contact,NULL);
    self.type=enemy.type=SITH_THING_PLAYER; self.sector=enemy.sector=&sector;
    self.collide=SITH_COLLIDE_SPHERE; self.collideSize=enemy.collideSize=.065f;
    enemy.collide=SITH_COLLIDE_FACE; enemy.position.y=.14f;
    enemy.orient.rvec.x=enemy.orient.lvec.y=enemy.orient.uvec.z=1;
    sector.pFirstThingInSector=&self; self.pNextThingInSector=&enemy;
    rdModel3 model={0}; rdMesh mesh={0}; rdFace face={0};
    int vertices[]={0,1,2,3};
    rdVector3 quad[]={{-.025f,0,-.003f},{.025f,0,-.003f},
                      {.025f,0,.003f},{-.025f,0,.003f}};
    face.numVertices=4; face.vertexPosIdx=vertices; face.normal.y=-1;
    mesh.aVertices=quad; mesh.faces=&face; mesh.numFaces=1;
    model.aGeos[0].numMeshes=1; model.aGeos[0].aMeshes=&mesh;
    enemy.renderData.type=RD_THING_MODEL3; enemy.renderData.model3=&model;
    /* Hook up the actor's ordinary aiming joints. */
    SithPuppetClass puppet={0};
    memset(puppet.aJoints,-1,sizeof(puppet.aJoints));
    puppet.aJoints[JOINTTYPE_TORSO]=0; puppet.aJoints[JOINTTYPE_PRIMARYWEAPJOINT]=1;
    rdVector3 joints[2]={0}; rdModel3 actorModel={0}; actorModel.numHNodes=2;
    self.orient=enemy.orient; self.pPuppetClass=&puppet; self.renderData.type=RD_THING_MODEL3;
    self.renderData.model3=&actorModel; self.renderData.hierarchyNodes2=joints;
    bot.frameDt=.020f; BT(TURN_RATE)=720;
    for (int sign=-1;sign<=1;sign+=2) {
        for (int i=0;i<4;i++) quad[i].z=sign*enemy.collideSize*.45f+(i<2 ? -.003f : .003f);
        assert(!Bot_SaberSeesBand(&self,&enemy,enemy.position,enemy.collideSize));
        rdVector3 aim=Bot_SaberAimPoint(&self,&enemy);
        assert(sign*aim.z>.025f && Bot_SaberSeesBand(&self,&enemy,aim,enemy.collideSize));
        self.actorParams.headPYR=(rdVector3){0};
        Bot_Aim(&self,aim,1);
        rdVector3 angles={.x=bot.rawPitch};
        sithActor_SetHeadPYR(&self,&angles);
        assert(sign*joints[0].x>0 && sign*joints[1].x>0);
        /* A closer player's collision sphere blocks the same ray. */
        blocker.type=SITH_THING_PLAYER; blocker.collide=SITH_COLLIDE_SPHERE;
        blocker.collideSize=.04f; blocker.position.y=.07f; blocker.sector=&sector;
        enemy.pNextThingInSector=&blocker;
        assert(!Bot_SaberSeesBand(&self,&enemy,aim,enemy.collideSize));
        assert(Bot_SaberAimPoint(&self,&enemy).z==0);
        enemy.pNextThingInSector=NULL;
    }
    assert(sithCollision_searchStackIdx==-1);
    puts("PASS stock JK collision and pose: centre rays miss both offset faces, tracked rays hit both, torso and weapon joint pitch follow each, foreground player occludes both");
}
