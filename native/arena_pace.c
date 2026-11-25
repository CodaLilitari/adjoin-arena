/* Timing hooks for the two Linux training images. Only the clock object uses
 * the virtual clocks. Transports, companion leases and the observer still see
 * the real monotonic clock. See build_arena_pace.py for the four call sites. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

enum { STEP_MS = 34 };
static unsigned rate;
static const char *role;
static uint64_t virtual_us, deadline_ns, frames;
/* jkMain's original outer cap is superseded by the pacer below. */
int arena_uncapped_fps;

extern void sithTime_Advance(void);
extern unsigned int sithTime_g_msecGameTime;
extern int sithTime_g_frameTime;
extern void SDL_Delay(uint32_t);

static uint64_t monotonic_ns(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) {
        perror("ARENA_PACE clock");
        exit(70);
    }
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + t.tv_nsec;
}

static void configure(void)
{
    if (rate) return;
    const char *r = getenv("ADJOIN_PACE_RATE");
    role = getenv("ADJOIN_PACE_ROLE");
    if (!r || (strcmp(r, "1") && strcmp(r, "2")) || !role ||
        (strcmp(role, "host") && strcmp(role, "dark") && strcmp(role, "light"))) {
        fputs("ARENA_PACE requires ADJOIN_PACE_RATE=1|2 and ADJOIN_PACE_ROLE=host|dark|light\n", stderr);
        exit(64);
    }
    rate = (unsigned)(r[0] - '0');
    virtual_us = monotonic_ns() / 1000;
}

uint32_t arena_clock_ms(void)
{
    configure();
    return (uint32_t)(virtual_us / 1000);
}

uint64_t arena_clock_us(void)
{
    configure();
    return virtual_us;
}

void arena_window_delay(uint32_t requested_ms)
{
    /* Yield when idle in the menu or waiting for traffic. The training clock
     * handles gameplay pacing, including the old bot-only 33 ms sleep. */
    SDL_Delay(requested_ms > 1 ? 1 : requested_ms);
}

void arena_advance(void)
{
    configure();
    const uint64_t period_ns = (uint64_t)STEP_MS * 1000000 / rate;
    uint64_t now = monotonic_ns();
    if (!deadline_ns || now > deadline_ns + period_ns * 2)
        deadline_ns = now; /* resume after loading or a stall, without skipping frames */
    deadline_ns += period_ns;
    struct timespec until = {
        (time_t)(deadline_ns / UINT64_C(1000000000)),
        (long)(deadline_ns % UINT64_C(1000000000))
    };
    int err;
    do {
        err = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &until, NULL);
    } while (err == EINTR);
    if (err) { errno = err; perror("ARENA_PACE sleep"); exit(70); }
    virtual_us += STEP_MS * 1000;
    sithTime_Advance();
    ++frames;
    if (frames == 1 || frames % 5 == 0) {
        fprintf(stderr, "ARENA_PACE role=%s pid=%ld rate=%u frame=%" PRIu64
                " game_ms=%u mono_ns=%" PRIu64 " step_ms=%u applied_ms=%d\n",
                role, (long)getpid(), rate, frames, sithTime_g_msecGameTime,
                monotonic_ns(), STEP_MS, sithTime_g_frameTime);
        fflush(stderr);
    }
}
