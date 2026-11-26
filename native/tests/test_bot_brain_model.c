/* BrainStore ADJOIN_EDGE_V1 artifact: SHA-256, strict parse, inference. */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "AI/jkBotBrainModel.h"

static int nearEq(float a, float b) { return fabsf(a - b) < 1e-5f; }

int main(void)
{
    char hex[65];
    jkBotBrain_Sha256Hex("", 0, hex);
    assert(!strcmp(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
    jkBotBrain_Sha256Hex("abc", 3, hex);
    assert(!strcmp(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    /* 56-byte FIPS vector exercises the two-block padding path. */
    jkBotBrain_Sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", 56, hex);
    assert(!strcmp(hex, "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"));

    const char *model = "ADJOIN_EDGE_V1 10\n"
        "0 0 0 0 0 0 0 0 0 0\n1 1 1 1 1 1 1 1 1 1\n"
        "20 0 0 0 0 0 0 0 0 0\n-5\n";
    char digest[65];
    jkBotBrain_Sha256Hex(model, strlen(model), digest);
    jkBotBrainEdgeModel parsed;
    assert(jkBotBrain_ParseEdgeModel(model, strlen(model), digest, &parsed));
    assert(parsed.loaded && !strcmp(parsed.digest, digest));
    float shortEdge[JKBOT_BRAIN_EDGE_FEATURES] = {0};
    shortEdge[0] = 0.25f;
    assert(nearEq(jkBotBrain_EdgeSuccess(&parsed, shortEdge), 0.5f));
    float longEdge[JKBOT_BRAIN_EDGE_FEATURES] = {0};
    longEdge[0] = 0.559f;
    assert(jkBotBrain_EdgeSuccess(&parsed, longEdge) > 0.99f);

    assert(!jkBotBrain_ParseEdgeModel(model, strlen(model),
        "0000000000000000000000000000000000000000000000000000000000000000", &parsed));
    assert(!parsed.loaded);
    assert(!jkBotBrain_ParseEdgeModel("ADJOIN_EDGE_V1 9\n", 17, NULL, &parsed));
    assert(!jkBotBrain_ParseEdgeModel(NULL, 0, NULL, &parsed));
    assert(nearEq(jkBotBrain_EdgeSuccess(NULL, shortEdge), 0.5f));
    printf("test_bot_brain_model: all checks passed\n");
    return 0;
}
