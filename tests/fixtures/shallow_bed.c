#include <assert.h>
#include <stddef.h>

typedef float flex_t;
typedef struct { unsigned flags; } SithSector;
typedef struct { unsigned flags; SithSector *pSector; void *pAdjoin; } SithSurface;
enum {
    SITH_SECTOR_NOGRAVITY=1, SITH_SECTOR_UNDERWATER=2, SITH_SECTOR_USETHRUST=8,
    SITH_SECTOR_FALLDEATH=0x40, SITH_SECTOR_NOACTORENTER=0x20,
    SITH_SURFACE_FLOOR=1, SITH_SURFACE_HAS_COLLISION=4, SITH_SURFACE_ICY=0x1000,
    SITH_SURFACE_VERYICY=0x2000, SITH_SURFACE_WATER=0x20000, SITH_SURFACE_VERYDEEPWATER=0x100000
};
#define BOT_FOOT_HEIGHT 0.120114f
static int Bot_SectorSafe(SithSector *s) {
    return s && !(s->flags & (SITH_SECTOR_FALLDEATH | SITH_SECTOR_NOACTORENTER));
}
#include "shallow_bed.h"

int main(void) {
    SithSector bed = {SITH_SECTOR_UNDERWATER}, body = {0};
    SithSurface floor = {0x20005, &bed, NULL};
    const float bgj_depth = 0.650938f - 0.620000f;
    assert(Bot_ShallowBed(&floor, bgj_depth, &body));
    assert(!Bot_ShallowBed(&floor, -1.0f, &body));
    assert(!Bot_ShallowBed(&floor, 0.10f, &body));
    assert(!Bot_ShallowBed(NULL, bgj_depth, &body));
    assert(!Bot_ShallowBed(&floor, bgj_depth, NULL));
    floor.pAdjoin = &body;
    assert(!Bot_ShallowBed(&floor, bgj_depth, &body));
    floor.pAdjoin = NULL;
    const unsigned bad_surfaces[] = {0x20004, 0x20001, 0x21005, 0x22005, 0x120005};
    for (size_t i=0; i<sizeof(bad_surfaces)/sizeof(bad_surfaces[0]); ++i) {
        floor.flags = bad_surfaces[i];
        assert(!Bot_ShallowBed(&floor, bgj_depth, &body));
    }
    floor.flags = 0x20005;
    const unsigned hazards[] = {SITH_SECTOR_NOGRAVITY, SITH_SECTOR_USETHRUST,
        SITH_SECTOR_FALLDEATH, SITH_SECTOR_NOACTORENTER};
    for (size_t i=0; i<sizeof(hazards)/sizeof(hazards[0]); ++i) {
        bed.flags = SITH_SECTOR_UNDERWATER | hazards[i];
        assert(!Bot_ShallowBed(&floor, bgj_depth, &body));
        bed.flags = SITH_SECTOR_UNDERWATER;
        body.flags = hazards[i];
        assert(!Bot_ShallowBed(&floor, bgj_depth, &body));
        body.flags = 0;
    }
    bed.flags = 0;
    assert(!Bot_ShallowBed(&floor, bgj_depth, &body));
    bed.flags = body.flags = SITH_SECTOR_UNDERWATER;
    assert(!Bot_ShallowBed(&floor, bgj_depth, &body));
    return 0;
}
