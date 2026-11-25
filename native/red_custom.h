/* Explicit local episode admission. Default callers retain stock discovery. */
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <openssl/evp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct { const char *episode,*map,*gobHash,*mapHash,*mode; } RedCustom;

static int Custom_Name(const char *s,int map)
{
    size_t n=strlen(s);
    if (!n || n>31) return 0;  /* stock advertised episode/level strings */
    if (map) {
        if (n<=4 || strcasecmp(s+n-4,".jkl")) return 0;
        n-=4;
    }
    for (size_t i=0;i<n;++i) {
        unsigned c=(unsigned char)s[i];
        if (!((c>='A'&&c<='Z') || (c>='a'&&c<='z') || (c>='0'&&c<='9') || c=='_' || c=='-')) return 0;
    }
    return 1;
}

static int Custom_Hex(const char *s)
{
    return strlen(s)==64 && strspn(s,"0123456789abcdef")==64;
}

static int Custom_Config(RedCustom *cfg)
{
    *cfg=(RedCustom){getenv("ADJOIN_CUSTOM_EPISODE"),getenv("ADJOIN_CUSTOM_MAP"),getenv("ADJOIN_CUSTOM_GOB_SHA256"),
                     getenv("ADJOIN_CUSTOM_MAP_SHA256"),getenv("ADJOIN_CUSTOM_MODE")};
    if (!cfg->episode && !cfg->map && !cfg->gobHash && !cfg->mapHash && !cfg->mode) return 0;
    if (!cfg->episode || !cfg->map || !cfg->gobHash || !cfg->mapHash || !cfg->mode ||
        !Custom_Name(cfg->episode,0) || !Custom_Name(cfg->map,1) || !Custom_Hex(cfg->gobHash) || !Custom_Hex(cfg->mapHash) ||
        (strcmp(cfg->mode,"ffa") && strcmp(cfg->mode,"tdm") && strcmp(cfg->mode,"ctf"))) return -1;
    return 1;
}

static int Custom_Loopback(const char *s)
{
    const char *p=NULL;
    if (s && !strncmp(s,"127.0.0.1:",10)) p=s+10;
    else if (s && !strncmp(s,"[::1]:",6)) p=s+6;
    if (!p || !*p || strlen(p)>5 || strspn(p,"0123456789")!=strlen(p)) return 0;
    long port=strtol(p,NULL,10);
    return port>0 && port<=65535;
}

static int Custom_Archive(const RedCustom *cfg)
{
    char path[64]="episode/"; size_t n=strlen(cfg->episode);
    for (size_t i=0;i<n;++i) path[8+i]=(char)tolower((unsigned char)cfg->episode[i]);
    strcpy(path+8+n,".gob");
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if (fd<0) return 0;
    struct stat st;
    EVP_MD_CTX *ctx=EVP_MD_CTX_new(); unsigned size=0; unsigned char hash[32],buf[65536];
    int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_size>0 && ctx && EVP_DigestInit_ex(ctx,EVP_sha256(),NULL);
    off_t total=0;
    while (ok) {
        ssize_t count=read(fd,buf,sizeof(buf));
        if (!count) break;
        if (count<0 && errno==EINTR) continue;
        if (count<0) { ok=0; break; }
        total+=count; ok=EVP_DigestUpdate(ctx,buf,(size_t)count);
    }
    if (ok) ok=total==st.st_size && EVP_DigestFinal_ex(ctx,hash,&size) && size==32;
    if (ctx) EVP_MD_CTX_free(ctx);
    close(fd);
    if (!ok) return 0;
    char hex[65];
    for (int i=0;i<32;++i) snprintf(hex+2*i,3,"%02x",hash[i]);
    return !strcmp(hex,cfg->gobHash);
}

static void Custom_Marker(const RedCustom *cfg,const char *phase)
{
    fprintf(stderr,"BOT_RED_CUSTOM phase=%s status=accepted episode=%s map=%s gob_sha=%s map_sha=%s mode=%s pid=%ld\n",
            phase,cfg->episode,cfg->map,cfg->gobHash,cfg->mapHash,cfg->mode,(long)getpid());
}

static int Custom_Admission(const char *endpoint,const char *episode,const char *map,int teams,int skins)
{
    RedCustom cfg; int enabled=Custom_Config(&cfg);
    if (!enabled) return 0;
    if (enabled<0 || !Custom_Loopback(endpoint) || !episode || !map || strcasecmp(episode,cfg.episode) ||
        strcasecmp(map,cfg.map) || teams!=!!strcmp(cfg.mode,"ffa") || (!strcmp(cfg.mode,"tdm") && !skins) ||
        !Custom_Archive(&cfg)) return -1;
    Custom_Marker(&cfg,"admission");
    return !strcmp(cfg.mode,"ctf") ? 2 : 1;
}

static int Custom_World(const char *map,const char *resolvedHash,const char *mode)
{
    RedCustom cfg; int enabled=Custom_Config(&cfg);
    if (!enabled) return 1;
    if (enabled<0 || !map || !resolvedHash || !mode || strcasecmp(cfg.map,map) ||
        strcmp(cfg.mapHash,resolvedHash) || strcmp(cfg.mode,mode)) return 0;
    Custom_Marker(&cfg,"world"); return 1;
}
