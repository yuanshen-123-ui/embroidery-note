<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 15 },
})

/* 全部为内联 SVG 图标（stroke 风格），替代 emoji */
const ICONS = {
  dice: '<rect x="3.5" y="3.5" width="17" height="17" rx="3.5"/><circle cx="8.3" cy="8.3" r="1.5" fill="currentColor" stroke="none"/><circle cx="15.7" cy="8.3" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="8.3" cy="15.7" r="1.5" fill="currentColor" stroke="none"/><circle cx="15.7" cy="15.7" r="1.5" fill="currentColor" stroke="none"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15H4.5A2.5 2.5 0 0 1 2 12.5v-8A2.5 2.5 0 0 1 4.5 2h8A2.5 2.5 0 0 1 15 4.5V5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  replay: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  needle: '<line x1="19" y1="5" x2="9.5" y2="14.5"/><ellipse cx="7.8" cy="16.2" rx="2.1" ry="3.4" transform="rotate(45 7.8 16.2)"/><path d="M5.8 18.2 3 21"/>',
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <svg
    :width="size" :height="size" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true" v-html="ICONS[name]"
  ></svg>
</template>
