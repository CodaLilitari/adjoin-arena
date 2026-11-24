/* Open flat ground at z=0 for movement checks: the floor ends at plainEdge
   and a wall stands at plainWall, both measured along +x. A shelf, when set,
   raises the floor to plainShelfZ from plainShelf onward behind a sheer face. */
static int testPlainActive;
static flex_t plainEdge=1e9f, plainWall=1e9f, plainShelf=1e9f, plainShelfZ;
static int plainSolidFloor; /* slanted rays meet the floor too (thrown grenades) */
static SithSector plainLand, plainPool;
static SithSurface plainGround;

static int TestPlainSphere(SithSector *sector) { return sector==&plainLand; }

static int TestPlainCollision(const rdVector3 *from,const rdVector3 *direction,
                              flex_t distance,flex_t radius,SithCollision *hit)
{
    rdVector3 end={from->x+direction->x*distance,from->y+direction->y*distance,
                   from->z+direction->z*distance};
    memset(hit,0,sizeof(*hit));
    hit->type=SITHCOLLISION_WORLD; hit->surface=&plainGround;
    plainGround.pSector=&plainLand;
    plainGround.flags|=SITH_SURFACE_HAS_COLLISION|SITH_SURFACE_FLOOR;
    if (direction->z<-0.99f) {
        flex_t floor=from->x>=plainShelf ? plainShelfZ : 0;
        if (from->x>=plainEdge || from->z<floor || end.z>floor) return 0;
        hit->distance=from->z-floor; hit->hitNorm.z=1;
        return 1;
    }
    if (Bot_Max(from->x,end.x)+radius>plainWall) { hit->hitNorm.x=-1; return 1; }
    if (plainShelf<1e8f) {
        /* Sample the swept body against the shelf's face and top. */
        int steps=(int)ceilf(distance/0.005f);
        for (int i=0;i<=steps;i++) {
            flex_t along=steps ? distance*i/steps : 0;
            flex_t x=from->x+direction->x*along, z=from->z+direction->z*along;
            if (x+radius>plainShelf && z-radius<plainShelfZ) {
                hit->distance=along; hit->hitNorm.x=-1; return 1;
            }
        }
    }
    if (plainSolidFloor && direction->z<0 && end.z-radius<0 && from->z-radius>=0) {
        hit->distance=(from->z-radius)/-direction->z; hit->hitNorm.z=1;
        return 1;
    }
    return 0;
}
