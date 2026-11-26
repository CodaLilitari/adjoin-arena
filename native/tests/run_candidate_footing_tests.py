"""Exercise the composed entrance and uphill floor probes in generated C."""
import argparse
from pathlib import Path
import subprocess
import tempfile


FIXTURE = """
#include <assert.h>
#include <stddef.h>
typedef float flex_t;
typedef struct {float x,y,z;} rdVector3;
typedef struct {int flags;} SithSector;
typedef struct {int flags; SithSector *sector;} SithThing;
typedef struct {SithSector *sector;} SithAdjoin;
typedef struct {int flags; SithAdjoin *pAdjoin; SithSector *pSector;} SithSurface;
typedef struct {int type; rdVector3 hitNorm; SithSurface *surface; SithThing *pThingCollided;
                float distance;} SithCollision;
enum {SITH_SECTOR_FALLDEATH=1, SITH_SECTOR_NOACTORENTER=2, SITH_TF_STANDABLE=4};
enum {SITHCOLLISION_ADJOINCROSS=1,SITHCOLLISION_WORLD=2,SITHCOLLISION_THING=4};
enum {RAYCAST_200=0x200,RAYCAST_800=0x800,RAYCAST_2000=0x2000,RAYCAST_10=0x10,
      SITH_SURFACE_WATER=1,SITH_SURFACE_VERYDEEPWATER=2};
#define BOT_FOOT_HEIGHT 0.075f
static struct World {SithThing aThings[2];} world;
static struct {struct World *world;} bot={&world};
static SithCollision next;
static int flags, count;
static SithSector *Bot_SectorAt(rdVector3 *p,SithSector *hint) {return hint;}
static int Bot_SectorSafe(SithSector *s) {return s && !s->flags;}
static int Bot_StaticFixture(SithThing *thing) {return thing!=NULL;}
static void sithCollision_SearchForCollisions(SithSector *s,void *self,rdVector3 *p,rdVector3 *v,
                                              float depth,float radius,int rays) {flags=rays;count=1;}
static SithCollision *sithCollision_PopStack(void) {return count-->0 ? &next : NULL;}
static void sithCollision_DecreaseStackLevel(void) {}
"""

CASES = """
int main(void)
{
    SithSector sector={0}, *support=NULL;
    SithThing *mesh=&world.aThings[1];
    rdVector3 position={0,0,1}, standing;
    int id=-1;
    mesh->sector=&sector;
    next.type=SITHCOLLISION_THING; next.pThingCollided=mesh; next.hitNorm.z=1;
    assert(Bot_Floor(position,&sector,1,&standing,&support));
    assert(!Bot_FloorWithFlags(position,&sector,1,&standing,&support,RAYCAST_10));
    assert(flags & RAYCAST_10);
    mesh->flags=SITH_TF_STANDABLE;
    assert(Bot_FloorWithFlags(position,&sector,1,&standing,&support,RAYCAST_10));
    sector.flags=SITH_SECTOR_FALLDEATH;
    assert(!Bot_Floor(position,&sector,1,&standing,&support));
    assert(Bot_StandingFloor(position,&sector,1,&standing,&support,1,&id,0));
    assert(id==1 && support==&sector && !(flags & RAYCAST_10));
    mesh->flags=0;
    assert(!Bot_StandingFloor(position,&sector,1,&standing,&support,1,&id,0));
    mesh->flags=SITH_TF_STANDABLE; sector.flags|=SITH_SECTOR_NOACTORENTER;
    assert(!Bot_StandingFloor(position,&sector,1,&standing,&support,1,&id,0));
    return 0;
}
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Staged navigation candidate")
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    core = (args.source / "src/AI/jkBot.c").read_text()
    start = core.index("static int Bot_StandingFloor(")
    end = core.index("static int Bot_ForceReady(", start)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "footing.c"
        source.write_text(FIXTURE + core[start:end] + CASES)
        exe = source.with_suffix(".exe")
        subprocess.run([args.cc, "-std=c11", source, "-o", exe], check=True)
        subprocess.run([exe], check=True)
    print("Ordinary, uphill and fall-death-sector footing cases passed.")
