/* Open flat ground at z=0 for movement checks: the floor ends at plainEdge
   and a wall stands at plainWall, both measured along +x. */
static int testPlainActive;
static flex_t plainEdge=1e9f, plainWall=1e9f;
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
        if (from->x>=plainEdge || from->z<0 || end.z>0) return 0;
        hit->distance=from->z; hit->hitNorm.z=1;
        return 1;
    }
    if (Bot_Max(from->x,end.x)+radius>plainWall) { hit->hitNorm.x=-1; return 1; }
    if (plainSolidFloor && direction->z<0 && end.z-radius<0 && from->z-radius>=0) {
        hit->distance=(from->z-radius)/-direction->z; hit->hitNorm.z=1;
        return 1;
    }
    return 0;
}
