"""Compile the final bridge crossing decision from a staged navigation candidate."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


TYPES = """
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
typedef float flex_t;
typedef struct {float x,y,z;} rdVector3;
typedef struct {int id,flags;} SithSector;
typedef struct Thing {int flags,type; rdVector3 position; float moveSize,collideSize;
                      SithSector *sector; struct Thing *attachedThing;} SithThing;
typedef struct {int sector,fixture; rdVector3 pos;} HintPoint;
enum {SITH_TF_STANDABLE=4,ENTRY_POINTS=10};
#define BOT_FOOT_HEIGHT .120114f
static HintPoint entryPoints[10]={[9]={7,-1,{-.605f,-8.855f,.120f}}};
static struct World {SithSector aSectors[8];SithThing aThings[2];} world;
static struct {struct World *world;float now;} bot={&world,1};
static struct {int ready,active,seq,trace;float nextLog;} hint={1,1,9,0,0};
static int obstacle, unsupported, calls;
static int Bot_SectorSafe(SithSector *s){return !s->flags;}
static int Bot_StaticFixture(SithThing *t){return t!=NULL;}
static int Bot_StandingFloor(rdVector3 p,SithSector *dest,float depth,rdVector3 *standing,
                             SithSector **on,int platforms,int *fixture,int flags) {
    calls++;
    *standing=p; standing->z=.120f; *on=dest;
    return calls!=unsupported;
}
static int Bot_Clear(SithThing *self,SithSector *s,rdVector3 a,rdVector3 b,float r,int flags) {
    return !obstacle;
}
static void Hint_Log(SithThing *self,const char *phase,const char *status,int f){}
"""

NEAR_FIELD = """
typedef struct {int flags; SithSector *sector;} SithSurfaceAdjoin;
typedef struct {SithSurfaceAdjoin *pAdjoin;} SithSurface;
typedef struct {unsigned type; float distance; SithThing *pThingCollided; SithSurface *surface;} SithCollision;
enum {RAYCAST_200=512,SITHCOLLISION_WORLD=2,SITHCOLLISION_THING=1,SITHCOLLISION_ADJOINCROSS=32,
      SITHSURF_ADJOIN_ALLOW_MOVEMENT=1,SITH_THING_ITEM=2,SITH_THING_WEAPON=3,SITH_THING_PARTICLE=4};
static SithCollision collision;
static int pop,stack;
static rdVector3 Bot_Sub(rdVector3 a,rdVector3 b){return (rdVector3){a.x-b.x,a.y-b.y,a.z-b.z};}
static float Bot_Len(rdVector3 a){return sqrtf(a.x*a.x+a.y*a.y+a.z*a.z);}
static float Bot_Min(float a,float b){return a<b?a:b;}
static void sithCollision_SearchForCollisions(SithSector *s,SithThing *owner,rdVector3 *p,
        rdVector3 *dir,float distance,float radius,int flags){
    assert(distance>0 && distance<=.05501f && radius==owner->collideSize);
    assert(stack==0);stack++;pop=1;
    if (obstacle) collision.type=SITHCOLLISION_WORLD;
}
static SithCollision *sithCollision_PopStack(void){return pop-->0 ? &collision : NULL;}
static void sithCollision_DecreaseStackLevel(void){assert(stack==1);stack--;}
"""

NEAR_TRIAL = """
    world.aSectors[7].flags=0;
    SithSurfaceAdjoin gate={SITHSURF_ADJOIN_ALLOW_MOVEMENT,&world.aSectors[7]};
    SithSurface surface={&gate}; world.aSectors[7].id=7;
    collision=(SithCollision){SITHCOLLISION_ADJOINCROSS,.01f,NULL,&surface};
    assert(Hint_Landing(&owner,&goal,181));
    gate.flags=0; assert(!Hint_Landing(&owner,&goal,181));
    gate.flags=SITHSURF_ADJOIN_ALLOW_MOVEMENT;gate.sector=&world.aSectors[6];
    assert(!Hint_Landing(&owner,&goal,181));
    collision=(SithCollision){SITHCOLLISION_THING,.01f,&mesh,NULL};
    assert(Hint_Landing(&owner,&goal,181));
    collision.pThingCollided=&world.aThings[1];assert(!Hint_Landing(&owner,&goal,181));
    collision=(SithCollision){SITHCOLLISION_WORLD,.02f,NULL,NULL};
    assert(!Hint_Landing(&owner,&goal,181) && stack==0);
"""
TRIAL = """
int main(void) {
    SithThing mesh={.flags=SITH_TF_STANDABLE};
    SithThing owner={.position={-.582f,-9.214f,.132f},.moveSize=.04f,.collideSize=.04f,
                     .sector=&world.aSectors[5],.attachedThing=&mesh};
    owner.sector->id=5;
    rdVector3 goal={0};
    assert(Hint_Landing(&owner,&goal,181) && calls==3);
    assert(goal.y==entryPoints[9].pos.y);
    for (int side=1;side<=3;side++) {
        calls=0;unsupported=side; assert(!Hint_Landing(&owner,&goal,181));
    }
    unsupported=0;obstacle=1; assert(!Hint_Landing(&owner,&goal,181));
    obstacle=0; assert(!Hint_Landing(&owner,&goal,182));
    mesh.flags=0; assert(!Hint_Landing(&owner,&goal,181)); mesh.flags=SITH_TF_STANDABLE;
    hint.seq=8; assert(!Hint_Landing(&owner,&goal,181));hint.seq=9;
    hint.ready=0; assert(!Hint_Landing(&owner,&goal,181));hint.ready=1;
    owner.position.x=-.49f; assert(!Hint_Landing(&owner,&goal,181));owner.position.x=-.582f;
    owner.position.y=-9.31f; assert(!Hint_Landing(&owner,&goal,181));owner.position.y=-9.214f;
    world.aSectors[7].flags=1; assert(!Hint_Landing(&owner,&goal,181));
}
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    hints = (args.source / "src/AI/jkBotRouteHints.inc").read_text()
    near = "static int Hint_LandingClear(" in hints
    start = "static int Hint_LandingClear(" if near else "static int Hint_Landing("
    code = hints[hints.index(start):hints.index("static int Hint_Walk(")]
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "landing.c"
        trial = TRIAL.rstrip()[:-1] + NEAR_TRIAL + "}" if near else TRIAL
        source.write_text(TYPES + (NEAR_FIELD if near else "") + code + trial)
        exe = source.with_suffix(".exe")
        subprocess.run([args.cc, "-std=c11", source, "-o", exe, *([] if os.name == "nt" else ["-lm"])], check=True)
        subprocess.run([exe], check=True)
    print("Original overlap and landing rejection cases passed.")
