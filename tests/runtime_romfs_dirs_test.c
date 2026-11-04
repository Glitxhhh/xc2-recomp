// Synthetic RomFS index and overlays behind OpenDirectory; no game files or storage roots are opened.
#include <assert.h>
#include "../runtime/host.h"
#undef HOST_OVERRIDE
#define HOST_OVERRIDE(sym, fn)
#include "../runtime/fs_host.c"
#define need romfs_need
#define lock romfs_lock
#include "../runtime/romfs.c"
#undef lock
#undef need

void rt_log(const char *fmt, ...) { (void)fmt; }
void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
void plat_mutex_lock(PlatMutex *m) { (void)m; }
void plat_mutex_unlock(PlatMutex *m) { (void)m; }
void plat_mutex_lock_shared(PlatMutex *m) { (void)m; }
void plat_mutex_unlock_shared(PlatMutex *m) { (void)m; }
int plat_fs_kind(const char *p) { (void)p; return PLAT_FS_MISSING; }
int plat_fs_list(const char *p, int (*cb)(const char *, int, uint64_t, void *), void *ctx) {
    (void)p; (void)cb; (void)ctx; abort();
}

static void test_directories(void) {
    static uint8_t fixture[1024];
    const char *names[] = {"folder-else/file", "folder/a.bin", "folder/sub/b.bin", "folder/sub/c.bin", "z.bin"};
    static char *new_names[] = {"added/file.bin", "folder/new.bin", "folder/sub/d.bin"};
    static Overlay patches[] = {{.index = 1, .size = 99}, {.index = 5, .size = 21},
                                {.index = 6, .size = 22}, {.index = 7, .size = 23}};
    index_bytes = fixture; file_count = 5; strings_offset = 24 + 5 * 24;
    size_t pos = 0;
    for (int i = 0; i < 5; i++) {
        Entry e = {.size = (uint64_t)(10 + i), .name = (uint32_t)pos, .len = (uint32_t)strlen(names[i]) + 1};
        memcpy(fixture + 24 + i * 24, &e, 24);
        strcpy((char *)fixture + strings_offset + pos, names[i]);
        pos += e.len;
    }
    added = new_names; nadded = 3; overlays = patches; noverlay = 4;
    strcpy(mount_name, "rom");
    uint64_t h;
    int64_t count;
    DirectoryEntry entries[8];
    assert(!open_directory(&h, "rom:/", 3));
    assert(!read_directory(&count, entries, h, 8) && count == 4);
    assert(!strcmp(entries[0].name, "added") && entries[0].type == FS_ENTRY_DIRECTORY);
    assert(!strcmp(entries[1].name, "folder-else") && !strcmp(entries[2].name, "folder"));
    assert(!strcmp(entries[3].name, "z.bin") && entries[3].size == 14);
    close_directory(h);
    assert(!open_directory(&h, "rom://folder/", 3));
    assert(!read_directory(&count, entries, h, 1) && count == 1 && !strcmp(entries[0].name, "a.bin"));
    assert(entries[0].size == 99 && entries[0].type == FS_ENTRY_FILE);
    assert(!read_directory(&count, entries, h, 8) && count == 2 && !strcmp(entries[0].name, "new.bin"));
    assert(entries[0].size == 22 && !strcmp(entries[1].name, "sub") && entries[1].size == 0);
    assert(!read_directory(&count, entries, h, 8) && !count);
    close_directory(h);
    for (int mode = 1; mode <= 2; mode++) {
        assert(!open_directory(&h, "rom:/folder", mode));
        assert(!read_directory(&count, entries, h, 8) && count == mode);
        assert(entries[0].type == (mode == 1 ? FS_ENTRY_DIRECTORY : FS_ENTRY_FILE));
        close_directory(h);
    }
    assert(!open_directory(&h, "rom:/added", 3));
    assert(!read_directory(&count, entries, h, 8) && count == 1 && entries[0].size == 21);
    close_directory(h);
    const char *missing[] = {"rom:/missing", "rom:/folder/a.bin", "rom:/fold", "rom:/folder/../sub", "rom:folder"};
    for (size_t i = 0; i < sizeof missing / sizeof *missing; i++)
        assert(open_directory(&h, missing[i], 3) == FS_R_PATH_NOT_FOUND);
    assert(open_directory(NULL, "rom:/", 3) == FS_R_INVALID_ARGUMENT);
    assert(open_directory(&h, "rom:/", 0) == FS_R_INVALID_ARGUMENT);
    file_count = nadded = noverlay = 0;
    assert(!open_directory(&h, "rom:/", 3));
    assert(!read_directory(&count, entries, h, 8) && !count);
    close_directory(h);
}
int main(void) {
    test_directories();
    puts("runtime RomFS: directory listings passed");
    return 0;
}
