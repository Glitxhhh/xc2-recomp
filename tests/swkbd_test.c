// Synthetic keyboard requests, without the guest SDK or a window. Run with tests/swkbd_test.py.
#include <assert.h>
#include "../runtime/swkbd.c"
#include "../runtime/ui_text.h"

#ifndef TEST_GAME_VERSION
#define TEST_GAME_VERSION 121
#endif
const int rt_game_version = TEST_GAME_VERSION;
static const char *answer = "<initial>";
static int windows;
const char *cfg_get(const char *key) { (void)key; return answer; }
void rt_log(const char *fmt, ...) { (void)fmt; }
_Noreturn void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
const char *ldr_describe(uint64_t addr, char *buf, int cap) { (void)addr; (void)buf; (void)cap; return "test"; }
int kern_core_away(void) { return 0; }
void kern_core_back(int *away) { (void)away; }
void plat_mutex_lock(PlatMutex *m) { assert(!m->p); m->p = m; }
void plat_mutex_unlock(PlatMutex *m) { assert(m->p == m); m->p = NULL; }
void input_block(int block) { (void)block; }
int text_entry_run(const SwkbdRequest *req, uint16_t *out, size_t cap, size_t *n) {
    *n = u16_len(req->initial, cap);
    memcpy(out, req->initial, *n * 2);
    windows++;
    return 1;
}

static void put32(uint8_t *p, int32_t x) { memcpy(p, &x, 4); }
static void put64(uint8_t *p, uint64_t x) { memcpy(p, &x, 8); }
static uint32_t show(uint8_t *arg, uint16_t *out) {
    uint64_t str[] = {(uintptr_t)out, 64};
    Cpu c = {.x = {(uintptr_t)str, (uintptr_t)arg}};
    memset(out, 0x55, 64);
    ov_show_keyboard(&c);
    return (uint32_t)c.x[0];
}

int main(void) {
    _Alignas(8) uint8_t arg[0x548] = {0};
    uint16_t out[32], initial[] = {'S', 't', 'a', 'r', 't', 0};
    SwkbdRequest req;
    put32(arg + KB_MAX_LEN, 9);
    request_from(arg, &req);
    assert(!req.initial[0] && !req.game_initial);
    assert(show(arg, out) == 0 && !out[0]);
    put32(arg + KB_MIN_LEN, 1);
    assert(show(arg, out) == SWKBD_CANCELED && !out[0]);
    put32(arg + KB_MIN_LEN, 0);
    answer = NULL;
    assert(show(arg, out) == 0 && !out[0] && windows == 1);
    answer = "<initial>";
    put64(arg + ARG_WORK, (uintptr_t)initial);
    put64(arg + ARG_WORK_SIZE, sizeof initial);
    put32(arg + KB_INIT_LEN, 5);
    request_from(arg, &req);
    assert(req.game_initial && !memcmp(req.initial, initial, sizeof initial));
    assert(show(arg, out) == 0 && !memcmp(out, initial, sizeof initial));
    answer = "<cancel>";
    assert(show(arg, out) == SWKBD_CANCELED && !out[0]);
    answer = "<initial>";
    put32(arg + KB_INIT_OFF, 100);  // Invalid work-buffer range must not invent starting text.
    assert(show(arg, out) == 0 && !out[0]);
    const char *languages[] = {"en", "ru", "ja", "fr", "de", "it", "es", "nl", "pt", "zh-Hans", "zh-Hant", "ko"};
    for (size_t l = 0; l < sizeof languages / sizeof *languages; l++)
        for (int id = UI_SWKBD_TITLE; id <= UI_SWKBD_PAD_HINT; id++)
            assert(ui_text_defined(languages[l], id));
    assert(!strcmp(ui_text_in("en", UI_SWKBD_PROMPT), "Enter text"));
    assert(!strcmp(ui_text_in("ru", UI_SWKBD_PROMPT), "Введите текст"));
    printf("keyboard %d: empty and game initial text, minimum length, cancel, invalid work range and 12 catalogs passed\n",
           rt_game_version);
}
