/* Optional Emscripten relink. Only the private practice launcher sets a rate.
 * Each real Sith update gets one 1/30 s control step. The original engine
 * subdivides it for physics and runs its ordinary multiplayer update. */
#include <emscripten.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>

extern int __real_sithUpdate(void);
extern void __real_sithTime_Advance(void);
extern void __real_sithThing_Update(float seconds, int milliseconds);
extern void __real_jkBot_Tick(float seconds);
extern void sithTime_SetFrameTime(int milliseconds);
extern float sithTime_g_frameTimeFlex, sithTime_g_fps;
extern uint32_t sithTime_g_msecGameTime;

EM_JS(int, requested_rate, (), {
    return location.hostname === '127.0.0.1' ? (globalThis.adjoinPracticeRate | 0) : 0;
});

static int rate = -1, active, steps, physics, controls, stalls;
static int physics_min_us, physics_max_us, control_min_us, control_max_us;
static double due;

static void count_step(float seconds, int *count, int *low, int *high)
{
    int us = (int)lround(seconds * 1000000.0);
    if (!*count || us < *low) *low = us;
    if (us > *high) *high = us;
    ++*count;
}

void __wrap_sithTime_Advance(void)
{
    if (!active) { __real_sithTime_Advance(); return; }
    /* Carry the integer remainder so 30 ticks advance the COG clock 1000 ms. */
    sithTime_SetFrameTime((steps % 3 == 2) ? 34 : 33);
    sithTime_g_frameTimeFlex = 1.0f / 30.0f;
    sithTime_g_fps = 30.0f;
}

void __wrap_sithThing_Update(float seconds, int milliseconds)
{
    if (active) count_step(seconds, &physics, &physics_min_us, &physics_max_us);
    __real_sithThing_Update(seconds, milliseconds);
}

void __wrap_jkBot_Tick(float seconds)
{
    if (active) count_step(seconds, &controls, &control_min_us, &control_max_us);
    __real_jkBot_Tick(seconds);
}

int __wrap_sithUpdate(void)
{
    if (rate < 0) rate = requested_rate();
    if (rate != 1 && rate != 2) return __real_sithUpdate();
    double now = emscripten_get_now(), period = 1000.0 / (30 * rate);
    if (!steps) due = now;
    if (now - due > 250) { due = now; ++stalls; }
    while (now >= due) {
        due += period;
        active = 1;
        int result = __real_sithUpdate();
        active = 0;
        ++steps;
        if (steps == 1 || steps % 15 == 0) {
            fprintf(stderr, "BOT_PRACTICE_CLOCK rate=%d ticks=%d physics=%d controls=%d game_ms=%u "
                    "wall_ms=%.3f physics_us=%d,%d control_us=%d,%d stalls=%d\n",
                    rate, steps, physics, controls, sithTime_g_msecGameTime, emscripten_get_now(),
                    physics_min_us, physics_max_us, control_min_us, control_max_us, stalls);
        }
        if (result) return result;
    }
    return 0;
}
