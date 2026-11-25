/* Bounded directed-edge costs learned from game-confirmed arrivals and stalls. */
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <time.h>
#include <unistd.h>

enum { NR_LIMIT=128, NR_AGE=86400, NR_DECAY=21600 };
typedef struct { uint64_t from,to; long touched; int mode,level; } NavEdgeRecord;
typedef struct {
    NavEdgeRecord rows[NR_LIMIT];
    int count, lock, loaded;
    char path[1024];
} NavRecall;

static int NR_Level(NavEdgeRecord r,long now)
{
    long age=now-r.touched;
    if (age<0 || age>=NR_AGE) return 0;
    int value=r.level-(int)(age/NR_DECAY);
    return value>0 ? value : 0;
}

static void NR_Open(NavRecall *n,const char *path,long now)
{
    memset(n,0,sizeof(*n)); n->lock=-1;
    if (!path || !*path || strlen(path)>=sizeof(n->path)) return;
    char lock[1100]; snprintf(lock,sizeof(lock),"%s.lock",path);
    n->lock=open(lock,O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW,0600);
    if (n->lock<0) return;
    if (flock(n->lock,LOCK_EX|LOCK_NB)) { close(n->lock); n->lock=-1; return; }
    strcpy(n->path,path);
    FILE *f=fopen(path,"r");
    if (!f) return;
    char line[160]; int seen=0;
    while (seen++<NR_LIMIT && fgets(line,sizeof(line),f)) {
        NavEdgeRecord r;
        char extra;
        if (sscanf(line,"%" SCNx64 " %" SCNx64 " %d %d %ld %c",&r.from,&r.to,&r.mode,&r.level,&r.touched,&extra)!=5 ||
            !r.from || !r.to || r.mode<0 || r.mode>64 || r.level<1 || r.level>4 || !NR_Level(r,now)) continue;
        n->rows[n->count++]=r;
    }
    fclose(f); n->loaded=n->count;
}

static int NR_Save(const NavRecall *n)
{
    if (n->lock<0) return 0;
    char tmp[1100]; snprintf(tmp,sizeof(tmp),"%s.tmp.XXXXXX",n->path);
    int fd=mkstemp(tmp);
    if (fd<0) return 0;
    FILE *f=fdopen(fd,"w");
    if (!f) { close(fd); unlink(tmp); return 0; }
    int ok=1;
    for (int i=0;i<n->count;++i) {
        NavEdgeRecord r=n->rows[i];
        if (fprintf(f,"%" PRIx64 " %" PRIx64 " %d %d %ld\n",r.from,r.to,r.mode,r.level,r.touched)<0) ok=0;
    }
    if (fclose(f)) ok=0;
    if (ok && !rename(tmp,n->path)) return 1;
    unlink(tmp); return 0;
}

static int NR_Find(const NavRecall *n,uint64_t from,uint64_t to,int mode)
{
    for (int i=0;i<n->count;++i)
        if (n->rows[i].from==from && n->rows[i].to==to && n->rows[i].mode==mode) return i;
    return -1;
}

/* No success-only state is needed. A success after a failure halves its
 * evidence rounded down; a failure increases the level up to four. */
static int NR_Observe(NavRecall *n,uint64_t from,uint64_t to,int mode,int failed,long now,int *before)
{
    int i=NR_Find(n,from,to,mode);
    *before=i<0 ? 0 : NR_Level(n->rows[i],now);
    int next=failed ? (*before<4 ? *before+1 : 4) : *before/2;
    if (!failed && i<0) return 0;
    if (!next) { n->rows[i]=n->rows[--n->count]; return 0; }
    if (i<0) {
        if (n->count<NR_LIMIT) i=n->count++;
        else {
            i=0;
            for (int j=1;j<n->count;++j) if (n->rows[j].touched<n->rows[i].touched) i=j;
        }
    }
    n->rows[i]=(NavEdgeRecord){from,to,now,mode,next};
    return next;
}
