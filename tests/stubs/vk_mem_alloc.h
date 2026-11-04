// Minimal declarations for tests/vk_texel_region_test.c and syntax checks without VMA installed.
// These are test types, not ABI-compatible allocation objects. Never put this directory on a runtime build's path.
#pragma once
#include <vulkan/vulkan.h>
typedef struct VmaAllocator_T *VmaAllocator;
typedef struct VmaAllocation_T *VmaAllocation;
typedef struct VmaDeviceMemoryCallbacks VmaDeviceMemoryCallbacks;
typedef struct { uint32_t memoryType; VkDeviceSize size; } VmaAllocationInfo;
typedef struct { int usage; } VmaAllocationCreateInfo;
enum { VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE = 8 };
void vmaGetAllocationInfo(VmaAllocator, VmaAllocation, VmaAllocationInfo *);
VkResult vmaBindImageMemory2(VmaAllocator, VmaAllocation, VkDeviceSize, VkImage, const void *);
VkResult vmaCreateImage(VmaAllocator, const VkImageCreateInfo *, const VmaAllocationCreateInfo *, VkImage *, VmaAllocation *, VmaAllocationInfo *);
VkResult vmaFlushAllocation(VmaAllocator, VmaAllocation, VkDeviceSize, VkDeviceSize);
VkResult vmaInvalidateAllocation(VmaAllocator, VmaAllocation, VkDeviceSize, VkDeviceSize);
void vmaDestroyBuffer(VmaAllocator, VkBuffer, VmaAllocation);
