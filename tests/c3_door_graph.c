/* Linked only with the full candidate bot TU in an external Windows build. */
struct HostServices *std_g_pHS;
static struct HostServices fakeHS;
static SithWorld c3World;
static SithSector cells[8];
static SithSurface faces[16];
static SithThing actors[76];
static sithCog cogs[8];
static SithCogScript scripts[8];
static SithCogSymbolTable tables[8];
static SithCogSymbol symbols[8][2];
static rdVector3 vertices[8 * 2 * 4];
static int indices[8 * 2 * 4];
static float held[85];
static int fileOpens, fakeVertices, modifiedCog;
static stdFile_t c3Open(const char *path, const char *mode)
{
    char buf[128];
    snprintf(buf, sizeof(buf), "%s", path);
    for (char *p = buf; *p; p++)
        if (*p == '\\')
            *p = '/';
    ++fileOpens;
    return (stdFile_t)fopen(buf, mode);
}
static int c3Size(stdFile_t fd)
{
    FILE *f = (FILE *)fd;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    rewind(f);
    return (int)n;
}
static size_t c3Read(stdFile_t fd, void *dest, size_t n)
{
    size_t read = fread(dest, 1, n, (FILE *)fd);
    if (modifiedCog && n == 1614 && read)
        ((unsigned char *)dest)[0] ^= 1;
    return read;
}
static int c3Close(stdFile_t fd) { return fclose((FILE *)fd); }
static int c3Sphere = (int)1;
static SithSector *c3Hint;
int sithIntersect_IsSphereInSector(const rdVector3 *p, flex_t radius, SithSector *cell)
{
    (void)p;
    (void)radius;
    return !!cell && c3Sphere;
}
SithSector *sithSector_FindSectorAtPos(SithWorld *world, rdVector3 *p)
{
    (void)world;
    (void)p;
    return c3Hint;
}
flex_t sithInventory_GetInventory(SithThing *self, int bin)
{
    (void)self;
    return held[bin];
}
static void c3Place(int idx, int thing, int team, int sas, int axis, float plane, float low, float high,
                    float base, float top)
{
    static SithPathFrame frames[8][2];
    SithThing *door = &actors[thing];
    SithSector *cell = &cells[idx];
    actors[thing].type = SITH_THING_COG;
    door->signature = 1000 + thing;
    door->moveType = SITH_MT_PATH;
    door->sector = cell;
    door->trackParams.loadedFrames = 2;
    door->trackParams.aFrames = frames[idx];
    cell->numSurfaces = 2;
    cell->surfaces = &faces[idx * 2];
    for (int s = 0; s < 2; s++) {
        SithSurface *surf = &cell->surfaces[s];
        surf->pAdjoin = (SithSurfaceAdjoin *)cell;
        rdFace *face = &surf->surfaceInfo.face;
        face->numVertices = 4;
        face->vertexPosIdx = &indices[fakeVertices];
        for (int v = 0; v < 4; v++) {
            float along = plane + (s ? .023f : -.023f), across = v < 2 ? low : high,
                  z = v == 1 || v == 2 ? top : base;
            vertices[fakeVertices] = (rdVector3){axis ? across : along, axis ? along : across, z};
            indices[fakeVertices] = fakeVertices;
            fakeVertices++;
        }
    }
    sithCog *c = &cogs[idx];
    c->pScript = &scripts[idx];
    strcpy(c->pScript->aName, sas         ? "c3_sascolored.cog"
                              : team == 1 ? "ctf_doorred.cog"
                                          : "ctf_doorgold.cog");
    c->pSymbolTable = &tables[idx];
    tables[idx].numUsedSymbols = tables[idx].tableSize = sas ? 2 : 1;
    tables[idx].aSymbols = symbols[idx];
    symbols[idx][0].pName = sas ? "door_int" : "door";
    symbols[idx][0].val.type = COG_TYPE_INT;
    symbols[idx][0].val.data[0] = thing;
    if (sas) {
        symbols[idx][1].pName = "sas_color";
        symbols[idx][1].val.type = COG_TYPE_INT;
        symbols[idx][1].val.data[0] = team;
    }
}
int main(void)
{
    fakeHS.fileOpen = c3Open;
    fakeHS.fileRead = c3Read;
    fakeHS.fileClose = c3Close;
    fakeHS.fileSize = c3Size;
    std_g_pHS = &fakeHS;
    bot.world = &c3World;
    c3World.aThings = actors;
    c3World.numThings = 75;
    c3World.numThingsLoaded = 76;
    c3World.aVertices = vertices;
    c3World.aCogs = cogs;
    c3World.numCogs = 6;
    c3Place(0, 23, 1, 0, 1, -.6375f, -2.725f, -2.475f, 2.525f, 2.780f);
    c3Place(1, 24, 1, 0, 0, -2.262481f, -1.875f, -1.625f, 2.525f, 2.780f);
    c3Place(2, 25, 2, 0, 0, -1.462481f, -1.875f, -1.625f, 2.525f, 2.780f);
    c3Place(3, 69, 2, 0, 0, -.443997f, -1.875f, -1.625f, 2.550f, 2.800f);
    c3Place(4, 72, 2, 1, 0, 3.287499f, 2.35f, 2.55f, 1.975f, 2.225f);
    c3Place(5, 74, 1, 1, 1, -.693702f, -5.714f, -5.514f, 2.275f, 2.525f);
    c3World.numVertices = fakeVertices;
    nav.ctf = 1;
    strcpy(c3World.map_jkl_fname, "c2.jkl");
    Bot_C3ReadDoors();
    assert(!c3Access.count && !fileOpens);
    strcpy(c3World.map_jkl_fname, "c3.jkl");
    nav.ctf = 0;
    Bot_C3ReadDoors();
    assert(!c3Access.count && !fileOpens);
    nav.ctf = 1;
    modifiedCog = 1;
    Bot_C3ReadDoors();
    assert(!c3Access.count);
    modifiedCog = 0;
    fileOpens = 0;
    Bot_C3ReadDoors();
    assert(c3Access.count == 6 && fileOpens == 4);
    SithThing *owner = &actors[0];
    assert(Bot_C3DeniedMask(owner) == 63);
    rdVector3 a = {3.532f, 2.441f, 2.070f}, enemyInterior = {3.1f, 2.44f, 2.07f},
              outside = {3.85f, 2.44f, 2.07f};
    assert(Bot_C3CrossingMask(a, enemyInterior) == 16 && Bot_C3CrossingMask(a, outside) == 0);
    /* Shortest registered crossing vs a longer legal walking path around its opening. */
    bot.nNodes = 4;
    bot.nodes[0].pos = a;
    bot.nodes[1].pos = enemyInterior;
    bot.nodes[2].pos = (rdVector3){a.x, 2.9f, a.z};
    bot.nodes[3].pos = (rdVector3){enemyInterior.x, 2.9f, a.z};
    for (int i = 0; i < 4; ++i)
        bot.nodes[i].sector = &cells[4];
    Bot_AddEdge(0, 1, BOT_ROUTE_WALK);
    Bot_AddEdge(0, 2, BOT_ROUTE_WALK);
    Bot_AddEdge(2, 3, BOT_ROUTE_WALK);
    Bot_AddEdge(3, 1, BOT_ROUTE_WALK);
    assert(bot.nodes[0].edges[0].c3Doors == 16 && bot.nodes[2].edges[0].c3Doors == 0);
    float distances[BOT_NODES];
    int parents[BOT_NODES];
    Bot_SearchPaths(owner, 0, distances, parents, 0);
    assert(parents[1] == 3);
    held[84] = 1;
    Bot_SearchPaths(owner, 0, distances, parents, 0);
    assert(parents[1] == 0);
    held[84] = 0;
    actors[72].curframe = 1;
    Bot_SearchPaths(owner, 0, distances, parents, 0);
    assert(parents[1] == 0);
    actors[72].curframe = 0;
    Bot_SearchPaths(owner, 0, distances, parents, 0);
    assert(parents[1] == 3);
    puts("actual edge registration and Dijkstra alternate route, held key, open and reclosed door "
         "passed");
    held[83] = 1;
    assert(Bot_C3DeniedMask(owner) == 28);
    held[84] = 1;
    assert(Bot_C3DeniedMask(owner) == 0);
    held[83] = held[84] = 0;
    actors[72].curframe = 1;
    assert(Bot_C3DeniedMask(owner) == 47);
    actors[72].trackParams.flags = 1;
    assert(Bot_C3DeniedMask(owner) == 63);
    actors[72].signature = 0;
    assert(Bot_C3DeniedMask(owner) == 47);
    strcpy(c3World.map_jkl_fname, "m4.jkl");
    Bot_C3ReadDoors();
    assert(Bot_C3DeniedMask(owner) == 0 && Bot_C3CrossingMask(a, enemyInterior) == 0);
    puts("full candidate stock map, live COG binding, inventory, frame, exterior, map-change checks "
         "passed");
    return 0;
}
