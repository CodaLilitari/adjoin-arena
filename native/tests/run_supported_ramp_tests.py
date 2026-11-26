"""Compile the patched Bot_WalkableSpan with controlled floor and clearance probes."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from run_stock_ground_tests import stock_function


FIXTURE = """
#include <assert.h>
#include <math.h>
#include <stddef.h>
typedef float flex_t;
typedef struct { float x,y,z; } rdVector3;
typedef struct { int id; } SithSector;
typedef struct { rdVector3 pos; SithSector *sector; } BotNode;
#define BOT_STEP_UP 0.25f
#define BOT_MAX_DROP 1.2f
#define RAYCAST_10 0x10
static float grade;
static int hole, discontinuity, ceiling, portal, collisionOnly;
static rdVector3 Bot_Sub(rdVector3 a,rdVector3 b) { return (rdVector3){a.x-b.x,a.y-b.y,a.z-b.z}; }
static float Bot_Horizontal(rdVector3 a) { return hypotf(a.x,a.y); }
static float Bot_Max(float a,float b) { return fmaxf(a,b); }
static rdVector3 Bot_Mix(rdVector3 a,rdVector3 b,float t)
{ return (rdVector3){a.x+t*(b.x-a.x),a.y+t*(b.y-a.y),a.z+t*(b.z-a.z)}; }
static int Bot_Clear(void *self,SithSector *sector,rdVector3 a,rdVector3 b,float radius,int fixed)
{ return !ceiling; }
static int Bot_PortalGroundClear(SithSector *s,rdVector3 a,rdVector3 b) { return !portal; }
static int Bot_FloorWithFlags(rdVector3 p,SithSector *s,float depth,rdVector3 *floor,SithSector **support,int flags)
{
    if ((flags & RAYCAST_10) && collisionOnly) return 0;
    if (hole && p.x>0.40f && p.x<0.60f) return 0;
    *floor=p;
    floor->z=discontinuity ? (p.x>0.5f ? grade : 0.0f) : p.x*grade;
    *support=s;
    return 1;
}
"""

CHECKS = """
int main(void)
{
    SithSector s={0}; BotNode a={{0,0,0},&s}, b={{1,0,0},&s}; int drop=0;
    assert(Bot_WalkableSpan(&a,&b,&drop,0.025f) && !drop);
    b.pos.z=grade=0.65f;
    assert(Bot_WalkableSpan(&a,&b,&drop,0.025f) && !drop);
    hole=1; assert(!Bot_WalkableSpan(&a,&b,&drop,0.025f)); hole=0;
    discontinuity=1; assert(!Bot_WalkableSpan(&a,&b,&drop,0.025f)); discontinuity=0;
    ceiling=1; assert(!Bot_WalkableSpan(&a,&b,&drop,0.025f)); ceiling=0;
    portal=1; assert(!Bot_WalkableSpan(&a,&b,&drop,0.025f)); portal=0;
    collisionOnly=1; assert(!Bot_WalkableSpan(&a,&b,&drop,0.025f)); collisionOnly=0;
    b.pos.z=grade=1.4f; assert(!Bot_WalkableSpan(&a,&b,&drop,0.025f));
    return 0;
}
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Patched engine tree")
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    function = stock_function(args.source, "AI/jkBotNavigation.inc", "Bot_WalkableSpan")
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "ramp.c"
        exe = Path(tmp) / "ramp.exe"
        program.write_text(FIXTURE + function + CHECKS)
        libraries = [] if os.name == "nt" else ["-lm"]
        subprocess.run([args.cc, "-std=c11", str(program), "-o", str(exe), *libraries], check=True)
        subprocess.run([str(exe)], check=True)
    print("Supported ramp and seven rejection/control cases passed.")
