/* Exercise the C3 candidate with two short parallel routes and stock door geometry. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef float flex_t;
typedef struct {
    float x, y, z;
} rdVector3;
static int Bot_NameIs(const char *a, const char *b) { return !strcmp(a, b); }

#ifdef C3_ACCESS_CANDIDATE
#include "jkBotC3Door.h"
#else
typedef struct {
    int axis;
    float plane, acrossMin, acrossMax, zMin, zMax;
} BotC3Opening;
static int Bot_C3ScriptBin(const char *name, int color)
{
    (void)name;
    (void)color;
    return 0;
}
static int Bot_C3Denied(int bin, int paired, float amount, int open) { return 0; }
static int Bot_C3Crosses(const BotC3Opening *p, rdVector3 a, rdVector3 b) { return 0; }
#endif

static int use_short_route(BotC3Opening *door, rdVector3 a, rdVector3 b, const char *script, int color,
                           flex_t red, flex_t gold, int open)
{
    int bin = Bot_C3ScriptBin(script, color);
    return !(Bot_C3Crosses(door, a, b) &&
             Bot_C3Denied(bin, !strcmp(script, "c3_sascolored.cog"), bin == 83 ? red : gold, open));
}

int main(void)
{
    BotC3Opening west = {0, -2.262481f, -1.875f, -1.625f, 2.525f, 2.779752f};
    rdVector3 room = {-2.046f, -1.758f, 2.620f}, beyond = {-2.5f, -1.75f, 2.62f};
    if (use_short_route(&west, room, beyond, "ctf_doorred.cog", 0, 0, 1, 0)) {
        fputs("closed stock red door admitted a bot with only the gold key\n", stderr);
        return 1;
    }
    assert(use_short_route(&west, room, beyond, "ctf_doorred.cog", 0, 1, 0, 0));
    assert(use_short_route(&west, room, beyond, "ctf_doorred.cog", 0, 0, 0, 1));
    assert(!use_short_route(&west, beyond, room, "ctf_doorred.cog", 0, 0, 1, 0));
    assert(!use_short_route(&west, room, beyond, "ctf_doorred.cog", 0, 2, 1, 0));
    assert(!use_short_route(&west, room, beyond, "ctf_doorgold.cog", 0, 1, 0, 0));
    assert(use_short_route(&west, room, beyond, "ctf_doorgold.cog", 0, 0, 1, 0));
    assert(!use_short_route(&west, room, beyond, "c3_sascolored.cog", 2, 1, 0, 0));
    assert(use_short_route(&west, room, beyond, "c3_sascolored.cog", 2, 0, 2, 0));
    assert(!use_short_route(&west, room, beyond, "c3_sascolored.cog", 1, 0, 1, 0));
    assert(use_short_route(&west, room, beyond, "c3_sascolored.cog", 1, 1, 0, 0));
    assert(use_short_route(&west, room, beyond, "c3_sascolored.cog", 3, 0, 0, 0));
    assert(use_short_route(&west, room, beyond, "c3_autodoor.cog", 0, 0, 0, 0));
    assert(use_short_route(&west, room, beyond, "unrelated.cog", 0, 0, 0, 0));
    assert(!Bot_C3Crosses(&west, room, (rdVector3){-2.10f, -1.758f, 2.62f}));
    assert(!Bot_C3Crosses(&west, (rdVector3){-2.0f, -1.3f, 2.62f}, (rdVector3){-2.6f, -1.3f, 2.62f}));
    assert(!Bot_C3Crosses(&west, (rdVector3){-2.0f, -1.75f, 3.1f}, (rdVector3){-2.6f, -1.75f, 3.1f}));
    assert(Bot_C3Crosses(&west, room, (rdVector3){west.plane, -1.75f, 2.62f}));
    BotC3Opening north = {1, -.69370f, -5.7139f, -5.5139f, 2.2750f, 2.5250f};
    assert(Bot_C3Crosses(&north, (rdVector3){-5.612f, -.563f, 2.37f}, (rdVector3){-5.61f, -.8f, 2.37f}));
    puts("C3 colored door access regression passed");
    return 0;
}
