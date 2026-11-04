// The software keyboard's front end for SDL windows (swkbd.h). Until the in-game text field exists (an ImGui entry in
// the menu overlay, which SDL_StartTextInput can pair with the Steam Deck's on-screen keyboard), the text entry takes
// the game's initial text at once, or cancels if it is empty. XC2_SWKBD_TEST=cancel stands for Cancel pressed, as in
// the Win32 window.
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "swkbd.h"

int text_entry_run(const SwkbdRequest *req, uint16_t *out, size_t cap, size_t *n) {
    const char *test = cfg_get("XC2_SWKBD_TEST");
    if (test && !strcmp(test, "cancel")) { *n = 0; return 0; }
    size_t k = 0;
    while (k < cap && req->initial[k]) k++;
    memcpy(out, req->initial, k * 2);
    *n = k;
    rt_log("swkbd: no text entry window on this host yet: %s", k ? "using the game's initial text" : "cancelled (no initial text)");
    return k > 0;
}
