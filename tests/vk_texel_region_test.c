// Exercise the real region and staging paths with Vulkan commands recorded in memory. No driver or game files.
// Run with tests/vk_texel_region_test.py; tests/stubs supplies only the VMA declarations this translation unit needs.
#include <assert.h>
#include <limits.h>
#include "../runtime/vk_texture.c"

static int logs, staging_calls, copy_calls;
static VkBufferImageCopy copied[8];
static uint32_t copied_count;
const char *cfg_get(const char *key) { (void)key; return NULL; }
void rt_log(const char *fmt, ...) { (void)fmt; logs++; }
uint64_t perf_begin(void) { return 0; }
void perf_end(int kind, uint64_t begin) { (void)kind; (void)begin; }
VkCtx *vk_ctx(void) { static VkCtx c; return &c; }
void *vk_staging(VkDeviceSize size, VkBuffer *buf, VmaAllocation *alloc) {
    void *p = calloc(1, size);
    assert(p); staging_calls++;
    *buf = (VkBuffer)(uintptr_t)p; *alloc = (VmaAllocation)p;
    return p;
}
void vmaDestroyBuffer(VmaAllocator a, VkBuffer b, VmaAllocation p) { (void)a; (void)b; free(p); }
VkResult vmaFlushAllocation(VmaAllocator a, VmaAllocation p, VkDeviceSize off, VkDeviceSize size) {
    (void)a; (void)p; (void)off; (void)size; return VK_SUCCESS;
}
VkResult vmaInvalidateAllocation(VmaAllocator a, VmaAllocation p, VkDeviceSize off, VkDeviceSize size) {
    (void)a; (void)p; (void)off; (void)size; return VK_SUCCESS;
}
VkCommandBuffer vk_upload_begin(void) { return (VkCommandBuffer)1; }
void vk_upload_end(void) {}
uint64_t vk_upload_flush(int wait) { (void)wait; return 0; }
void rc_vkCmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo *di) { (void)cb; (void)di; }
static void record(uint32_t n, const VkBufferImageCopy *r) {
    assert(n <= 8); copy_calls++; copied_count = n; memcpy(copied, r, n * sizeof *r);
}
void rc_vkCmdCopyBufferToImage(VkCommandBuffer cb, VkBuffer b, VkImage i, VkImageLayout l, uint32_t n,
                             const VkBufferImageCopy *r) { (void)cb; (void)b; (void)i; (void)l; record(n, r); }
void rc_vkCmdCopyImageToBuffer(VkCommandBuffer cb, VkImage i, VkImageLayout l, VkBuffer b, uint32_t n,
                             const VkBufferImageCopy *r) { (void)cb; (void)b; (void)i; (void)l; record(n, r); }
int vk_astc_gpu(void) { return 0; }
int vk_astc_record(VkCommandBuffer cb, VkBuffer src, VkDeviceSize size, const VkAstcRegion *r, int n,
                   uint32_t bw, uint32_t bh, int srgb, VkImage i, VkImageAspectFlags aspect, VkBuffer out) {
    abort();
}
void astc_decode_ldr_mt(const uint8_t *blocks, uint32_t w, uint32_t h, uint32_t bw, uint32_t bh, bool srgb, uint8_t *out) {
    abort();
}

static tex_t texture(int target, uint32_t w, uint32_t h, uint32_t depth, uint32_t levels, int format) {
    tex_t t = {.d = {.target = target, .width = w, .height = h, .depth = depth, .levels = levels, .format = format}};
    nvn_tex_layout(&t.d, &t.L);
    return t;
}

int main(void) {
    tex_t t = texture(NVN_TEXTURE_TARGET_2D_ARRAY, 16, 8, 4, 3, NVN_FORMAT_RGBA8);
    view_t v = {.set_levels = 1, .base_level = 1, .set_layers = 1, .min_layer = 1, .nlayers = 3};
    NVNcopyRegion r = {.xoffset = 2, .yoffset = 1, .zoffset = 1, .width = 6, .height = 3, .depth = 2};
    Region g;
    assert(region_of(&t, &v, &r, 32, 128, &g));
    assert(g.level == 1 && g.layer0 == 1 && g.nz == 2 && g.row == 32 && g.img == 128);
    Tex e = {.t = t, .pub = {.width = 16, .height = 8, .depth = 1, .layers = 4, .levels = 3, .samples = 1}};
    uint8_t data[256] = {0};
    for (int write = 0; write <= 1; write++) {
        assert(image_texels(&e, &g, &r, data, write));
        assert(copied_count == 2 && copied[0].imageSubresource.mipLevel == 1);
        assert(copied[0].imageSubresource.baseArrayLayer == 2 && copied[1].imageSubresource.baseArrayLayer == 3);
        assert(copied[0].imageOffset.x == 2 && copied[0].imageOffset.y == 1 && copied[0].imageOffset.z == 0);
        assert(copied[0].imageExtent.width == 6 && copied[0].imageExtent.height == 3 && copied[0].imageExtent.depth == 1);
    }
    // The image may have fewer levels or layers than the guest descriptor. Neither direction may allocate or copy.
    for (int bad = 0; bad < 5; bad++) {
        Tex invalid = e;
        if (bad == 0) invalid.pub.levels = 1;
        if (bad == 1) invalid.pub.layers = 3;
        if (bad == 2) invalid.pub.width = 8;
        if (bad == 3) invalid.pub.height = 4;
        if (bad == 4) invalid.pub.samples = 4;
        int stages = staging_calls, copies = copy_calls, messages = logs;
        for (int write = 0; write <= 1; write++) assert(!image_texels(&invalid, &g, &r, data, write));
        assert(staging_calls == stages && copy_calls == copies && logs == messages + 2);
    }
    for (int field = 0; field < 6; field++) {
        NVNcopyRegion invalid = r;
        switch (field) {
        case 0: invalid.xoffset++; break;
        case 1: invalid.yoffset++; break;
        case 2: invalid.zoffset++; break;
        case 3: invalid.width++; break;
        case 4: invalid.height++; break;
        case 5: invalid.depth++; break;
        }
        assert(!region_of(&t, &v, &invalid, 0, 0, &g));
    }
    NVNcopyRegion invalid = r;
    invalid.xoffset = INT_MAX; assert(!region_of(&t, &v, &invalid, 0, 0, &g));
    invalid = r; invalid.width = INT_MAX; assert(!region_of(&t, &v, &invalid, 0, 0, &g));
    invalid = r; invalid.zoffset = -1; assert(!region_of(&t, &v, &invalid, 0, 0, &g));
    v.base_level = 32; assert(!region_of(&t, &v, &r, 0, 0, &g));
    v.base_level = 3; assert(!region_of(&t, &v, &r, 0, 0, &g));
    v.base_level = 1; v.min_layer = 4; assert(!region_of(&t, &v, &r, 0, 0, &g));
    v.min_layer = 1; v.nlayers = 2; assert(!region_of(&t, &v, &r, 0, 0, &g));
    v.nlayers = 3;
    assert(!region_of(&t, &v, &r, 23, 0, &g));
    assert(!region_of(&t, &v, &r, UINT64_MAX, 0, &g));
    assert(!region_of(&t, &v, &r, 32, 87, &g));
    assert(!region_of(&t, &v, &r, 32, UINT64_MAX, &g));
    t = texture(NVN_TEXTURE_TARGET_3D, 8, 8, 8, 3, NVN_FORMAT_RGBA8);
    v = (view_t){.set_levels = 1, .base_level = 1};
    r = (NVNcopyRegion){.width = 4, .height = 4, .zoffset = 2, .depth = 2};
    assert(region_of(&t, &v, &r, 0, 0, &g));
    e = (Tex){.t = t, .pub = {.width = 8, .height = 8, .depth = 8, .layers = 1, .levels = 3, .samples = 1}};
    assert(image_texels(&e, &g, &r, data, 1));
    assert(copied[0].imageSubresource.baseArrayLayer == 0 && copied[0].imageOffset.z == 2 && copied[1].imageOffset.z == 3);
    r.depth = 3; assert(!region_of(&t, &v, &r, 0, 0, &g));
    r.depth = 0; assert(region_of(&t, &v, &r, 0, 0, &g) && g.nz == 1);
    t = texture(NVN_TEXTURE_TARGET_1D_ARRAY, 8, 99, 3, 1, NVN_FORMAT_RGBA8);
    r = (NVNcopyRegion){.width = 8, .height = 1, .depth = 3};
    assert(region_of(&t, NULL, &r, 0, 0, &g));
    r.height = 2; assert(!region_of(&t, NULL, &r, 0, 0, &g));
    t = texture(NVN_TEXTURE_TARGET_CUBEMAP, 8, 8, 1, 1, NVN_FORMAT_RGBA8);
    r = (NVNcopyRegion){.width = 8, .height = 8, .depth = 6};
    assert(region_of(&t, NULL, &r, 0, 0, &g));
    r.depth = 7; assert(!region_of(&t, NULL, &r, 0, 0, &g));
    t = texture(NVN_TEXTURE_TARGET_2D, 10, 7, 1, 1, NVN_FORMAT_RGBA_DXT1);
    r = (NVNcopyRegion){.xoffset = 4, .yoffset = 4, .width = 6, .height = 3, .depth = 1};
    assert(region_of(&t, NULL, &r, 0, 0, &g));
    r.width = 5; assert(!region_of(&t, NULL, &r, 0, 0, &g));
    r.width = 6; r.xoffset = 2; assert(!region_of(&t, NULL, &r, 0, 0, &g));
    puts("regions: mip/layer/3D bounds, overflow, strides, compressed edges, recorded valid copies and rejected image copies passed");
}
